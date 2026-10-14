"""Regression tests for the measurement claims made by the P1/P2 receiver."""

import csv
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from diagnostics.wifi_receiver import (
    Burst, Capture, FIELD_NAMES, Session, configuration_verified,
    missing_ranges, parse_packet, timing_summary,
)


def sample(index=0, seq=100, burst=1, boot=77, timestamp=None):
    values = [3, 1, boot, burst, index, seq,
              timestamp if timestamp is not None else seq * 5000, 5000,
              0, 0, 2048, 16, 0, 0,
              0, 0, 1, 16 / 16.4, 0, 0, 0, 0, 1, 0.1, 0, 0, 14]
    return parse_packet(",".join(map(str, values)).encode("ascii"))


def encoded_sample(p):
    return ",".join(str(p[k]) for k in FIELD_NAMES).encode("ascii")


def sender(burst=1, attempts=3, accepted=3, closed=True, boot=77):
    return dict(v=3, type="burst", node=1, boot=boot, id=burst, closed=closed,
                first_seq=100, last_seq=100 + attempts - 1, first_us=500000,
                last_us=500000 + (attempts - 1) * 5000,
                attempted=attempts, accepted=accepted, failed=attempts - accepted)


def timing(produced=401, bursts=0):
    n = produced - 1
    return dict(v=3, type="timing", node=1, boot=77, state="STREAMING",
                produced=produced, intervals=n, sum_dt_us=5000 * n,
                min_dt_us=5000, max_dt_us=5000, hist=[0, 0, n, 0, 0, 0],
                skipped_deadlines=0, max_late_us=10, max_read_us=600,
                max_processing_us=100, max_wifi_us=1000, dropped=0, high_water=1,
                attempted=0, accepted=0, failed=0, diag_failed=0,
                bursts_started=bursts, active_burst=0, idle_samples=produced,
                idle_gyro_sum=[0, 0, 0], idle_accel_sum=[0, 0, produced])


def configuration():
    return dict(v=3, type="config", node=1, boot=77, state="STREAMING", produced=0,
                verified=True, who=0x44, gyro_config=0x27, accel_config=0x27, pwr_mgmt=15,
                gyro_fs_dps=2000, accel_fs_g=16, gyro_lsb_per_dps=16.4,
                accel_lsb_per_g=2048, period_us=5000, calibration_samples=400,
                gyro_bias_counts=[1.2, -2.3, 4.5], accel_offset_g=[0.01, 0.02, 0.03],
                alpha=0.2, gyro_start_dps=40, gyro_stop_dps=15,
                accel_start_g=0.3, accel_stop_g=0.15, quiet_ms=150)


def transport(report=1, failures=0):
    return dict(v=3, type="transport", node=1, boot=77, produced=401,
                report=report, backend="lwip_nonblocking_v1", time_ms=2000,
                attempted=100, accepted=100-failures, failed=failures,
                data_failed=failures, control_failed=0,
                stages=[0, 0, failures, 0], errors=[failures, 0, 0, 0],
                last_errno=12 if failures else 0, last_stage=3 if failures else 0,
                last_data=bool(failures), last_ms=1900 if failures else 0,
                last_bytes=200 if failures else 0, last_sent=-1 if failures else 0,
                last_wifi=3, last_rssi=-50, last_rssi_age_ms=900, last_heap=180000,
                wifi_status=3, rssi_dbm=-49, disconnects=0,
                last_disconnect_reason=0, last_disconnect_ms=0,
                heap_free=180000, heap_min=175000)


class ProtocolTests(unittest.TestCase):
    def test_sample_and_control_round_trip(self):
        self.assertEqual(sample()["az_raw"], 2048)
        self.assertEqual(sample()["status_flags"], 14)
        for packet in (configuration(), timing(), sender(), transport(), transport(failures=4)):
            self.assertEqual(parse_packet(json.dumps(packet).encode()), packet)

    def test_transport_rejects_inconsistent_or_malformed_counters(self):
        for key, value in (("failed", 5), ("stages", [0, 0, 3, 0]),
                           ("errors", [0, 0, 0]), ("data_failed", 0),
                           ("rssi_dbm", float("nan")), ("last_stage", 5),
                           ("last_data", 1), ("backend", "unknown")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                p = transport(failures=4)
                p[key] = value
                parse_packet(json.dumps(p).encode())

    def test_transport_json_fits_firmware_buffer_at_numeric_bounds(self):
        p = transport()
        for key, value in list(p.items()):
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                p[key] = 4294967295  # conservative even for byte-sized fields
            elif isinstance(value, list):
                p[key] = [4294967295]*len(value)
        self.assertLess(len(json.dumps(p, separators=(",", ":")))+1, 1152)

    def test_old_firmware_rejected_clearly(self):
        with self.assertRaisesRegex(ValueError, "flash"):
            parse_packet(b"2,1,100,500000")

    def test_malformed_or_nonfinite_rejected(self):
        for payload in (b"", b"{", b"3,1,2", encoded_sample(sample()).replace(b"0.1", b"nan")):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_packet(payload)
        p = sender(accepted=2)
        p["failed"] = 0
        with self.assertRaises(ValueError):
            parse_packet(json.dumps(p).encode())
        t = timing()
        t["hist"][0] = 1
        with self.assertRaises(ValueError):
            parse_packet(json.dumps(t).encode())

    def test_gyro_readback_must_agree_with_scale(self):
        c = configuration()
        self.assertTrue(configuration_verified(c))
        c["gyro_config"] = 0x07  # the original mismatch
        self.assertFalse(configuration_verified(c))
        c["gyro_config"] = 0x27
        c["gyro_lsb_per_dps"] = 8.2
        self.assertFalse(configuration_verified(c))

    def test_timestamp_wrap_retains_unsigned_device_values(self):
        first = sample(timestamp=0xFFFFFF00)
        second = sample(1, 101, timestamp=(0xFFFFFF00 + 5000) & 0xFFFFFFFF)
        self.assertEqual((second["timestamp_us"] - first["timestamp_us"]) & 0xFFFFFFFF, 5000)
        self.assertEqual(second["interval_us"], 5000)


class DeliveryTests(unittest.TestCase):
    def test_duplicate_is_not_extra_delivery(self):
        b = Burst()
        for i in (0, 1, 1, 2):
            b.add_sample(sample(i, 100 + i))
        b.add_summary(sender())
        self.assertEqual(b.summary()["accepted_not_received"], 0)
        self.assertEqual(b.summary()["duplicates"], 1)
        self.assertEqual(b.summary()["received_unique"], 3)

    def test_late_reordered_packet_fills_previously_missing_index(self):
        b = Burst()
        b.add_sample(sample(0))
        b.add_sample(sample(2, 102))
        b.add_summary(sender())
        self.assertEqual(b.summary()["accepted_not_received"], 1)
        b.add_sample(sample(1, 101))
        self.assertEqual(b.summary()["accepted_not_received"], 0)
        self.assertEqual(b.summary()["reordered"], 1)

    def test_lost_first_last_or_entire_burst_is_counted(self):
        b = Burst()
        b.add_summary(sender())
        self.assertEqual(b.summary()["accepted_not_received"], 3)
        b.add_sample(sample(1, 101))
        self.assertEqual(b.summary()["accepted_not_received"], 2)
        self.assertEqual(b.summary()["unreceived_attempt_indexes"]["ranges"], [[0, 0], [2, 2]])

    def test_local_send_failure_separate_from_accepted_not_received(self):
        b = Burst()
        b.add_sample(sample(0))
        b.add_sample(sample(2, 102))
        b.add_summary(sender(accepted=2))
        self.assertEqual(b.summary()["local_send_failures"], 1)
        self.assertEqual(b.summary()["accepted_not_received"], 0)

    def test_complete_send_failure_cannot_look_like_successful_delivery(self):
        s = Session(1, 77)
        s.ingest(sender(attempts=41, accepted=0), 1)
        result = s.summary()["finalized_burst_totals"]
        self.assertEqual(result["not_captured"], 41)
        self.assertEqual(result["received_percent_of_attempted"], 0)
        self.assertEqual(result["accepted_not_received"], 0)  # not the total loss metric

    def test_total_absent_counts_both_local_failures_and_later_nonreceipt(self):
        s = Session(1, 77)
        s.ingest(sender(attempts=4, accepted=3), 1)
        s.ingest(sample(0), 2)
        s.ingest(sample(1, 101), 3)
        result = s.summary()["finalized_burst_totals"]
        self.assertEqual(result["local_send_failures"], 1)
        self.assertEqual(result["accepted_not_received"], 1)
        self.assertEqual(result["not_captured"], 2)
        self.assertEqual(result["received_percent_of_attempted"], 50)

    def test_missing_final_summary_is_unknown(self):
        b = Burst()
        b.add_sample(sample())
        b.add_summary(sender(attempts=1, accepted=1, closed=False))
        self.assertIsNone(b.summary()["accepted_not_received"])

    def test_bursts_are_not_inferred_from_time_or_acquisition_gaps(self):
        c = Capture()
        c.ingest(sample(0, 100, burst=1), 0)
        c.ingest(sample(1, 101, burst=1), 10)  # > old 0.2s timeout, same burst
        c.ingest(sender(1, 2, 2), 10)
        c.ingest(sample(0, 1000, burst=2), 10.01)  # < old timeout, new burst
        c.ingest(sender(2, 1, 1), 10.02)
        result = c.summary()["sessions"][0]
        self.assertEqual(len(result["bursts"]), 2)
        self.assertEqual(result["finalized_burst_totals"]["accepted_not_received"], 0)

    def test_reboot_has_separate_sequence_space(self):
        c = Capture()
        c.ingest(sample(0, 100, boot=77), 0)
        c.ingest(sample(0, 0, boot=88), 1)
        self.assertEqual(len(c.sessions), 2)

    def test_repeated_summaries_and_old_progress_are_idempotent(self):
        b = Burst()
        b.add_summary(sender())
        b.add_summary(sender())
        b.add_summary(sender(attempts=1, accepted=1, closed=False))
        self.assertEqual(b.summary()["sender_attempted"], 3)
        self.assertEqual(b.summary()["conflicting_packets"], 0)

    def test_inconsistent_counts_are_not_negative_loss(self):
        b = Burst()
        b.add_sample(sample(0))
        b.add_sample(sample(5, 105))
        b.add_summary(sender(attempts=1, accepted=1))
        self.assertFalse(b.summary()["counts_consistent"])
        self.assertIsNone(b.summary()["accepted_not_received"])

    def test_timing_counts_expose_wholly_unseen_bursts(self):
        s = Session(1, 77)
        s.ingest(timing(bursts=3), 1)
        s.ingest(sample(burst=2), 2)
        self.assertEqual(s.summary()["unseen_burst_count"], 2)
        self.assertEqual(s.summary()["unseen_burst_ids"]["ranges"], [[1, 1], [3, 3]])

    def test_large_missing_range_is_bounded(self):
        r = missing_ranges({0, 999999999}, 1000000000)
        self.assertEqual(r["ranges"], [[1, 999999998]])


class TimingTests(unittest.TestCase):
    def test_old_firmware_has_explicitly_unavailable_transport_diagnostics(self):
        s = Session(1, 77)
        s.ingest(timing(), 1)
        self.assertIsNone(s.summary()["transport"])

    def test_transport_snapshots_are_ordered_and_do_not_change_motion_state(self):
        s = Session(1, 77)
        s.ingest(timing(), 1)
        s.ingest(transport(report=3, failures=4), 2)
        s.ingest(transport(report=2, failures=0), 3)
        self.assertEqual(s.summary()["transport"]["failed"], 4)
        self.assertEqual(s.latest_state, "STREAMING")

    def test_rate_uses_number_of_intervals_not_number_of_samples(self):
        t = timing_summary(timing())
        self.assertEqual(t["achieved_hz"], 200)
        self.assertEqual(t["mean_interval_us"], 5000)
        self.assertEqual(t["within_4500_5499_percent"], 100)

    def test_delayed_heartbeat_does_not_roll_back_counters(self):
        s = Session(1, 77)
        s.ingest(timing(1001), 1)
        s.ingest(timing(401), 2)
        self.assertEqual(s.summary()["timing"]["produced"], 1001)

    def test_startup_and_calibration_evidence(self):
        s = Session(1, 77)
        c = configuration()
        s.ingest(c, 1)
        s.ingest(timing(), 2)
        self.assertTrue(s.summary()["observed_startup"])
        self.assertTrue(s.summary()["range_readback_verified"])
        self.assertEqual(s.summary()["timing"]["gate_idle_mean_calibrated_accel_g"], [0, 0, 1])

    def test_delayed_config_cannot_hide_a_reported_fault(self):
        s = Session(1, 77)
        fault = timing()
        fault["state"] = "FAULT"
        s.ingest(fault, 1)
        s.ingest(configuration(), 2)
        self.assertEqual(s.summary()["state"], "FAULT")


class LoopbackCaptureTests(unittest.TestCase):
    def test_real_udp_capture_writes_reusable_evidence(self):
        script = Path(__file__).resolve().parents[1] / "diagnostics" / "wifi_receiver.py"
        with tempfile.TemporaryDirectory(prefix="cg4002-receiver-test-") as temporary:
            self.assertTrue(Path(temporary).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()))
            out = Path(temporary) / "capture"
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            process = subprocess.Popen([
                sys.executable, "-B", str(script), "--bind", "127.0.0.1", "--port", str(port),
                "--duration", "1.5", "--output", str(out), "--power-source", "lipo-usb-disconnected",
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
                    # Repeat to tolerate process startup; duplicates must not inflate delivery.
                    deadline = time.monotonic() + 1.0
                    while time.monotonic() < deadline:
                        packets = [configuration(), sample(2, 102), sample(0), sample(1, 101), sender(), timing(bursts=1), transport()]
                        for p in packets:
                            data = encoded_sample(p) if p["type"] == "sample" else json.dumps(p).encode()
                            tx.sendto(data, ("127.0.0.1", port))
                        time.sleep(0.05)
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
            result = json.loads((out / "summary.json").read_text())
            s = result["sessions"][0]
            self.assertEqual(s["bursts"]["1"]["accepted_not_received"], 0)
            self.assertEqual(s["bursts"]["1"]["received_unique"], 3)
            self.assertGreater(s["bursts"]["1"]["duplicates"], 0)
            self.assertEqual(s["timing"]["achieved_hz"], 200)
            self.assertTrue(s["range_readback_verified"])
            self.assertEqual(s["transport"]["backend"], "lwip_nonblocking_v1")
            self.assertIn("[transport]", stdout)
            with (out / "samples.csv").open(newline="") as stream:
                self.assertGreater(len(list(csv.DictReader(stream))), 3)
            self.assertIn("FINAL CAPTURE SUMMARY", stdout)
            self.assertTrue((out / "diagnostics.jsonl").stat().st_size)


if __name__ == "__main__":
    unittest.main()
