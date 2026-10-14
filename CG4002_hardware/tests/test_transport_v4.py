"""Batch/retry protocol and capture-window regressions; no hardware required."""
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from diagnostics.wifi_receiver import Session, parse_packet, parse_datagram, timing_summary, describe_timing
from diagnostics.demo_receiver import DemoModel
from test_capture_receiver import configuration, sample, sender, timing, transport, encoded_sample


def queued_report(report=1, offered=10, accepted=10, dropped=0, pending=0, recovered=5):
    return dict(v=4, type="txqueue", node=1, boot=77, produced=401, report=report,
                offered=offered, accepted=accepted, dropped=dropped, pending=pending,
                recovered=min(recovered, accepted), overflow=0, expired=dropped,
                permanent=0, cancelled=0, calls=4, errors=2, retries=2, datagrams=2,
                high_water=max(10, pending), max_age_ms=60, oldest_ms=0,
                capacity=128, batch_size=5, flush_ms=20, max_age_limit_ms=1000, retry_ms=10)


def v4sample(index=0, seq=100, burst=1):
    p = sample(index, seq, burst)
    p["version"] = 4
    return p


def v4burst(attempts=3, accepted=1, pending=2, gate_closed=True):
    p = sender(attempts=attempts, accepted=accepted, closed=gate_closed and pending == 0)
    p.update(v=4, pending=pending, gate_closed=gate_closed, failed=attempts-accepted-pending)
    return p


class QueuedProtocolTests(unittest.TestCase):
    def test_imu_health_and_interruption_preserved(self):
        p = timing()
        p.update(v=4, imu_read_failures=21, imu_consecutive=0, imu_max_consecutive=20,
                 imu_recovery_attempts=2, imu_recoveries=1, saturated_samples=150)
        s = Session(1, 77)
        s.ingest(parse_packet(json.dumps(p).encode()), 0)
        self.assertIn("imu_read_failures=21 imu_recoveries=1 saturated=150", describe_timing(s))
        b = v4burst(accepted=3, pending=0)
        b["interrupted"] = True
        s.ingest(parse_packet(json.dumps(b).encode()), 1)
        self.assertTrue(s.bursts[1].summary()["interrupted"])
        for invalid in (-1, True, 1.5):
            p["imu_read_failures"] = invalid
            with self.assertRaises(ValueError):
                parse_packet(json.dumps(p).encode())

    def test_recovered_streaming_supersedes_fault_after_new_acquisition(self):
        s = Session(1, 77)
        fault = timing(401)
        fault["state"] = "FAULT"
        s.ingest(fault, 0)
        s.ingest(timing(402), 1)
        self.assertEqual(s.latest_state, "STREAMING")
        s.ingest(fault, 2)
        self.assertEqual(s.latest_state, "STREAMING")

    def test_staggered_diagnostic_cost_preserved_and_optional(self):
        p = timing()
        self.assertIsNone(timing_summary(p)["max_diagnostic_service_us"])
        p.update(v=4, max_diag_us=1800)
        parsed = parse_packet(json.dumps(p).encode())
        s = Session(1, 77)
        s.ingest(parsed, 0)
        self.assertEqual(s.summary()["timing"]["max_diagnostic_service_us"], 1800)
        self.assertIn("max_diagnostic_us=1800", describe_timing(s))
        for invalid in (-1, True, 1.5, None):
            p["max_diag_us"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_packet(json.dumps(p).encode())

    def test_staggered_configuration_marker_retained(self):
        p = configuration()
        p.update(v=4, diag_scheduler="staggered_v1", telemetry_headroom_us=3500)
        s = Session(1, 77)
        s.ingest(parse_packet(json.dumps(p).encode()), 0)
        self.assertEqual(s.summary()["configuration"]["diag_scheduler"], "staggered_v1")

    def test_batch_expands_without_changing_sample_identity(self):
        rows = [v4sample(i, 100+i) for i in range(5)]
        payload = b"\n".join(encoded_sample(p) for p in rows) + b"\n"
        self.assertEqual(parse_datagram(payload), rows)
        self.assertEqual(parse_datagram(encoded_sample(sample())), [sample()])

    def test_malformed_batch_rejected_atomically(self):
        good = encoded_sample(v4sample())
        for payload in (good+b"\n4,1", good+b"\n"+encoded_sample(v4sample(2, 102)),
                        good+b"\n"+encoded_sample(v4sample(1, 101, burst=2)),
                        b"\n".join([good]*6), good+b"\n"+json.dumps(timing()).encode()):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_datagram(payload)

    def test_pending_is_not_a_final_drop(self):
        for p in (v4burst(), queued_report(pending=2, accepted=8)):
            self.assertEqual(parse_packet(json.dumps(p).encode()), p)
        p = timing()
        p.update(v=4, attempted=3, accepted=1, failed=0, pending=2)
        self.assertEqual(parse_packet(json.dumps(p).encode()), p)

    def test_cannot_finalize_with_pending_samples(self):
        p = v4burst()
        p["closed"] = True
        with self.assertRaisesRegex(ValueError, "finalization"):
            parse_packet(json.dumps(p).encode())

    def test_queue_counter_inconsistencies_rejected(self):
        for key, value in (("pending", 1), ("offered", 11), ("expired", 1),
                           ("calls", 5), ("recovered", 11), ("retries", 5),
                           ("capacity", 0), ("batch_size", 6)):
            p = queued_report()
            p[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_packet(json.dumps(p).encode())

    def test_progress_settlement_cannot_roll_back(self):
        s = Session(1, 77)
        s.ingest(configuration(), 0)
        s.ingest(v4burst(), 1)
        s.ingest(v4burst(accepted=2, pending=1), 2)
        s.ingest(v4burst(), 3)
        self.assertEqual(s.bursts[1].sender["pending"], 1)
        s.ingest(v4burst(accepted=3, pending=0), 4)
        s.ingest(v4burst(), 5)
        self.assertTrue(s.bursts[1].summary()["complete_sender_summary"])
        self.assertEqual(s.bursts[1].summary()["local_send_failures"], 0)

    def test_queue_reports_ordered(self):
        s = Session(1, 77)
        s.ingest(queued_report(report=3), 1)
        s.ingest(queued_report(report=2, accepted=8, pending=2), 2)
        self.assertEqual(s.txqueue["report"], 3)

    def test_gate_can_stop_while_transmission_still_pending(self):
        model = DemoModel(clock=lambda: 10, console=False)
        model.on_packet(configuration(), 0)
        model.on_packet(v4sample(), 9)
        model.on_packet(v4burst(), 10)
        result = model.snapshot()
        self.assertEqual(result["state"], "settled")
        self.assertEqual(result["summary"]["capture_delivery"]["finalized_burst_ids"], [])
        self.assertEqual(result["summary"]["bursts"]["1"]["pending_samples"], 2)

    def test_late_retry_does_not_reopen_gate(self):
        model = DemoModel(clock=lambda: 10, console=False)
        model.on_packet(configuration(), 0)
        model.on_packet(v4burst(), 9)
        model.on_packet(v4sample(index=1, seq=101), 10)
        self.assertEqual(model.snapshot()["state"], "settled")


class CaptureWindowTests(unittest.TestCase):
    def test_restart_receiver_same_boot_does_not_inherit_loss(self):
        s = Session(1, 77)
        baseline = timing(produced=20201, bursts=7)
        baseline.update(attempted=2402, accepted=2324, failed=78)
        s.ingest(baseline, 0)
        for i in range(1, 8):
            s.ingest(sender(burst=i), 1)  # old summary replay: no old samples here
        self.assertEqual(s.summary()["capture_delivery"]["sender_attempted"], 0)
        new = sender(burst=8, attempts=1953, accepted=1857)
        new.update(first_seq=22035, last_seq=23987)
        for i in range(1857):
            s.ingest(sample(i, 22035+i, burst=8), 2)
        s.ingest(new, 3)
        final = timing(produced=30001, bursts=8)
        final.update(attempted=4355, accepted=4181, failed=174)
        s.ingest(final, 4)
        result = s.summary()
        d = result["capture_delivery"]
        self.assertEqual(d["sender_attempted"], 1953)
        self.assertEqual(d["received_unique"], 1857)
        self.assertEqual(d["local_send_failures"], 96)
        self.assertEqual(d["accepted_not_received"], 0)
        self.assertEqual(len(d["historical_burst_ids"]), 7)
        self.assertEqual(d["bursts_started"], 1)
        self.assertEqual(result["capture_counter_changes"]["failed"], 96)

    def test_partially_observed_burst_excluded_not_claimed_lossless(self):
        s = Session(1, 77)
        s.ingest(sample(1, 101), 0)
        s.ingest(sender(), 1)
        d = s.summary()["capture_delivery"]
        self.assertEqual(d["partial_burst_ids"], ["1"])
        self.assertIsNone(d["received_percent_of_attempted"])

    def test_whole_new_burst_lost_still_counts(self):
        s = Session(1, 77)
        s.ingest(timing(produced=50), 0)
        s.ingest(sender(attempts=3, accepted=0), 1)
        d = s.summary()["capture_delivery"]
        self.assertEqual(d["local_send_failures"], 3)
        self.assertEqual(d["received_percent_of_attempted"], 0)

    def test_history_alone_cannot_define_capture_window(self):
        s = Session(1, 77)
        s.ingest(sender(), 0)
        d = s.summary()["capture_delivery"]
        self.assertIsNone(d["start_seq"])
        self.assertEqual(d["sender_attempted"], 0)
        s.ingest(timing(produced=401, bursts=1), 1)
        self.assertEqual(s.summary()["capture_delivery"]["historical_burst_ids"], ["1"])

    def test_delayed_packet_cannot_move_window_backwards(self):
        s = Session(1, 77)
        s.ingest(timing(produced=401, bursts=1), 0)
        s.ingest(configuration(), 1)
        s.ingest(sender(), 2)
        self.assertEqual(s.capture_start_seq, 401)
        self.assertEqual(s.summary()["capture_delivery"]["historical_burst_ids"], ["1"])

    def test_first_error_snapshot_is_a_baseline_not_a_new_warning(self):
        model = DemoModel(clock=lambda: 3, console=False)
        model.on_packet(timing(), 0)
        model.on_packet(transport(failures=4), 1)
        self.assertEqual(model.snapshot()["summary"]["capture_transport_changes"]["failed"], 0)
        self.assertFalse(any("Send errors" in e["text"] for e in model.events))
        model.on_packet(transport(report=2, failures=7), 2)
        self.assertEqual(model.snapshot()["summary"]["capture_transport_changes"]["failed"], 3)

    def test_recovered_errors_do_not_become_final_sample_drops(self):
        s = Session(1, 77)
        s.ingest(configuration(), 0)
        s.ingest(queued_report(), 1)
        self.assertEqual(s.summary()["capture_queue_changes"]["recovered"], 5)
        self.assertEqual(s.summary()["capture_queue_changes"]["dropped"], 0)


class BatchLoopbackTests(unittest.TestCase):
    def test_real_socket_batches_duplicates_and_invalid_batch(self):
        script = Path(__file__).resolve().parents[1] / "diagnostics" / "wifi_receiver.py"
        with tempfile.TemporaryDirectory(prefix="cg4002-v4-test-") as temporary:
            out = Path(temporary) / "capture"
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            process = subprocess.Popen([sys.executable, "-B", str(script), "--bind", "127.0.0.1",
                "--port", str(port), "--duration", "3", "--output", str(out)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic()+5
                while time.monotonic() < deadline:
                    if (out/"capture.log").exists() and "Listening" in (out/"capture.log").read_text():
                        break
                    time.sleep(.02)
                self.assertIn("Listening", (out/"capture.log").read_text())
                batch = b"\n".join(encoded_sample(v4sample(i, 100+i)) for i in range(5))
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
                    for p in (json.dumps(configuration()).encode(), batch, batch,
                              batch+b"\n4,broken", json.dumps(v4burst(5, 5, 0)).encode(),
                              json.dumps(queued_report(offered=5, accepted=5)).encode()):
                        tx.sendto(p, ("127.0.0.1", port))
                _, stderr = process.communicate(timeout=7)
                self.assertEqual(process.returncode, 0, stderr)
                result = json.loads((out/"summary.json").read_text())
                self.assertEqual(result["invalid_packets"], 1)
                self.assertEqual(result["sessions"][0]["bursts"]["1"]["duplicates"], 5)
                self.assertEqual(result["sessions"][0]["capture_delivery"]["received_unique"], 5)
                self.assertEqual(result["sessions"][0]["capture_delivery"]["not_captured"], 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()


if __name__ == "__main__":
    unittest.main()
