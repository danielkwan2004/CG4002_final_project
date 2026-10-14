"""UI semantics, protocol ordering, HTTP and real UDP capture regression tests."""

import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from diagnostics.demo_receiver import DemoModel, make_server, replay_records
from test_capture_receiver import configuration, encoded_sample, sample, sender, timing, transport


class DemoStateTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.model = DemoModel(clock=lambda: self.now, console=False)

    def ingest(self, p, now=None):
        if now is not None:
            self.now = now
        self.model.on_packet(p, self.now)

    def state(self):
        return self.model.snapshot()["state"]

    def test_waiting_calibrating_settled_moving_closed(self):
        self.assertEqual(self.state(), "waiting")
        c = configuration()
        c["state"] = "CALIBRATING"
        self.ingest(c)
        self.assertEqual(self.state(), "calibrating")
        self.ingest(configuration())
        self.assertEqual(self.state(), "unknown")
        self.ingest(timing(50))
        self.assertEqual(self.state(), "settled")
        self.ingest(sample())
        self.assertEqual(self.state(), "moving")
        self.ingest(sender(attempts=1, accepted=1))
        self.assertEqual(self.state(), "settled")

    def test_lost_link_is_not_a_motion_stop(self):
        self.ingest(sample())
        self.now += 4
        self.assertEqual(self.state(), "disconnected")
        self.assertFalse(any("Motion stopped" in e["text"] for e in self.model.events))
        self.ingest(timing(401))
        self.assertEqual(self.state(), "settled")

    def test_calibration_has_longer_heartbeat_grace(self):
        c = configuration()
        c["state"] = "CALIBRATING"
        self.ingest(c)
        self.now += 5
        self.assertEqual(self.state(), "calibrating")
        self.now += 4
        self.assertEqual(self.state(), "disconnected")

    def test_idle_heartbeat_keeps_connection_alive_without_samples(self):
        for i in range(20):
            self.ingest(timing(201+i*200), 10+i)
            self.assertEqual(self.state(), "settled")
        self.assertIsNone(self.model.snapshot()["latest"])

    def test_old_close_cannot_stop_a_new_burst(self):
        self.ingest(sample(burst=2, seq=200))
        self.ingest(sender())
        self.assertEqual(self.state(), "moving")
        self.assertEqual(self.model.snapshot()["burst"], 2)

    def test_old_timing_and_duplicates_cannot_reopen_closed_burst(self):
        self.ingest(sample())
        self.ingest(sender(attempts=1, accepted=1))
        self.ingest(sample())
        t = timing(50, 1)
        t["active_burst"] = 1
        self.ingest(t)
        self.assertEqual(self.state(), "settled")
        self.assertEqual(self.model.snapshot()["duplicates"], 1)
        self.assertEqual(sum("Motion detected" in e["text"] for e in self.model.events), 1)

    def test_lost_end_packet_can_be_resolved_by_new_idle_heartbeat(self):
        self.ingest(sample())
        self.ingest(timing(401, 1))
        snapshot = self.model.snapshot()
        self.assertEqual(snapshot["state"], "settled")
        self.assertEqual(snapshot["summary"]["bursts_without_final_summary"], ["1"])
        self.assertEqual(snapshot["summary"]["finalized_burst_totals"]["received_unique"], 0)

    def test_late_sample_cannot_roll_back_displayed_values(self):
        self.ingest(sample(2, 102), 10)
        self.ingest(sample(0, 100), 11)
        self.assertEqual(self.model.snapshot()["sample_age_s"], 1)
        self.assertEqual(len(self.model.points), 1)

    def test_idle_values_are_held_not_fabricated_zeros(self):
        self.ingest(sample(), 10)
        self.ingest(timing(401), 12)
        result = self.model.snapshot()
        self.assertEqual(result["sample_age_s"], 2)
        self.assertEqual(result["latest"]["gyro"], [0.1, 0, 0])
        self.assertEqual(result["state"], "settled")

    def test_new_boot_clears_chart_and_retired_boot_cannot_return(self):
        self.ingest(sample())
        self.ingest(sample(seq=0, boot=88))
        self.ingest(timing(1001))  # stale previous boot 77
        self.assertEqual(self.model.snapshot()["summary"]["boot"], 88)
        self.assertEqual(self.model.latest_seq, 0)
        self.assertEqual(len(self.model.points), 1)

    def test_other_nodes_do_not_mix(self):
        p = configuration()
        p["node"] = 2
        self.ingest(p)
        self.assertEqual(self.state(), "waiting")

    def test_invalid_packets_are_disclosed_without_implying_connection(self):
        self.model.on_invalid(ValueError("old firmware"), self.now)
        self.assertEqual(self.model.snapshot()["invalid_packets"], 1)
        self.assertEqual(self.state(), "waiting")
        self.assertIn("Unrecognized packet", self.model.events[0]["text"])

    def test_transport_failure_event_is_not_a_motion_event(self):
        self.ingest(transport(failures=0), 9)
        self.ingest(sample(), 10)
        self.ingest(transport(report=2, failures=4), 11)
        self.assertEqual(self.state(), "moving")
        self.assertEqual(self.model.snapshot()["summary"]["transport"]["failed"], 4)
        self.assertIn("Send errors:", self.model.events[0]["text"])
        count = len(self.model.events)
        self.ingest(transport(report=2, failures=4), 12)
        self.assertEqual(len(self.model.events), count)

    def test_fault_overrides_samples_and_old_configuration(self):
        t = timing()
        t["state"] = "FAULT"
        self.ingest(t)
        self.ingest(configuration())
        self.ingest(sample())
        self.assertEqual(self.state(), "fault")

    def test_repeated_old_evidence_does_not_prove_current_motion(self):
        self.ingest(sample(), 10)
        self.ingest(configuration(), 14)
        self.assertEqual(self.state(), "unknown")

    def test_ui_histories_bounded_and_replay_completion_explicit(self):
        for i in range(800):
            self.ingest(sample(i, i+100), 10+i*0.1)
        self.assertEqual(len(self.model.points), 700)
        self.assertLessEqual(len(self.model.events), 12)
        self.model.mode = "replay"
        self.model.on_finish({}, self.now)
        self.assertEqual(self.state(), "complete")
        self.assertEqual(self.model.snapshot()["mode"], "replay")


class DemoHttpTests(unittest.TestCase):
    def test_200hz_loopback_with_and_without_dashboard_polling(self):
        """Synthetic local workload, not a physical Wi-Fi capacity measurement."""
        root = Path(__file__).resolve().parents[1]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with tempfile.TemporaryDirectory(prefix="cg4002-200hz-test-") as temporary:
            for protocol, dashboard in ((3, False), (3, True), (4, False), (4, True)):
                with self.subTest(protocol=protocol, dashboard=dashboard):
                    out = Path(temporary) / (f"v{protocol}-" + ("dashboard" if dashboard else "console"))
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                        probe.bind(("127.0.0.1", 0))
                        udp_port = probe.getsockname()[1]
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                        probe.bind(("127.0.0.1", 0))
                        http_port = probe.getsockname()[1]
                    script = root / ("demo_receiver.py" if dashboard else "diagnostics/wifi_receiver.py")
                    command = [sys.executable, "-B", str(script), "--bind", "127.0.0.1",
                               "--port", str(udp_port), "--duration", "4", "--output", str(out)]
                    if dashboard:
                        command += ["--no-browser", "--http-port", str(http_port)]
                    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    stop = threading.Event()
                    polls = []
                    def poll_dashboard():
                        while not stop.is_set():
                            try:
                                with opener.open(f"http://127.0.0.1:{http_port}/api/state", timeout=1) as response:
                                    polls.append(json.load(response))
                            except (OSError, urllib.error.URLError):
                                pass  # startup/shutdown; successful polls are asserted below
                            stop.wait(.05)
                    thread = threading.Thread(target=poll_dashboard, daemon=True) if dashboard else None
                    if thread:
                        thread.start()
                    try:
                        deadline = time.monotonic()+5
                        while time.monotonic() < deadline:
                            if (out / "capture.log").exists() and "Listening" in (out / "capture.log").read_text():
                                break  # file creation precedes bind; wait for actual receiver readiness
                            time.sleep(.02)
                        self.assertIn("Listening", (out / "capture.log").read_text())
                        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
                            target = ("127.0.0.1", udp_port)
                            config = configuration()
                            config["v"] = protocol
                            tx.sendto(json.dumps(config).encode(), target)
                            start = time.monotonic()
                            count = 400
                            batch = []
                            for i in range(count):
                                delay = start+i*.005-time.monotonic()
                                if delay > 0:
                                    time.sleep(delay)
                                p = sample(i, i)
                                p["version"] = protocol
                                batch.append(encoded_sample(p))
                                if protocol == 3 or len(batch) == 5:
                                    tx.sendto(b"\n".join(batch), target)
                                    batch.clear()
                            b = sender(attempts=count, accepted=count)
                            b.update(first_seq=0, last_seq=count-1, first_us=0, last_us=(count-1)*5000)
                            t = timing(count, 1)
                            t.update(attempted=count, accepted=count, idle_samples=0, idle_accel_sum=[0,0,0])
                            b["v"] = t["v"] = protocol
                            if protocol == 4:
                                b.update(gate_closed=True, pending=0)
                                t["pending"] = 0
                            for _ in range(3):
                                for p in (b, t, transport()):
                                    tx.sendto(json.dumps(p).encode(), target)
                                time.sleep(.02)
                        stdout, stderr = process.communicate(timeout=7)
                        self.assertEqual(process.returncode, 0, stderr)
                        result = json.loads((out / "summary.json").read_text())["sessions"][0]
                        self.assertEqual(result["finalized_burst_totals"]["received_unique"], count)
                        self.assertEqual(result["finalized_burst_totals"]["not_captured"], 0)
                        self.assertEqual(result["finalized_burst_totals"]["received_percent_of_attempted"], 100)
                        self.assertEqual(result["capture_delivery"]["received_unique"], count)
                        if dashboard:
                            self.assertGreater(len(polls), 10)
                            self.assertTrue(any(p["summary"] and p["summary"]["bursts"] for p in polls))
                    finally:
                        stop.set()
                        if thread:
                            thread.join(timeout=2)
                        if process.poll() is None:
                            process.kill()
                            process.communicate()

    def test_static_assets_state_and_no_file_browsing(self):
        model = DemoModel(console=False)
        server = make_server(model, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        # Do not use environment HTTP proxies for localhost tests.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            for path in ("/", "/app.js", "/style.css", "/api/state"):
                with opener.open(url+path, timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
                    self.assertTrue(response.read())
            with self.assertRaises(urllib.error.HTTPError) as error:
                opener.open(url+"/../wifi_receiver.py", timeout=2)
            self.assertEqual(error.exception.code, 404)
            request = urllib.request.Request(url+"/api/state", headers={"Host":"attacker.invalid"})
            with self.assertRaises(urllib.error.HTTPError) as error:
                opener.open(request, timeout=2)
            self.assertEqual(error.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_real_demo_receiver_keeps_evidence_and_friendly_events(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="cg4002-demo-test-") as temporary:
            out = Path(temporary) / "capture"
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            process = subprocess.Popen([
                sys.executable, "-B", str(root / "demo_receiver.py"), "--no-browser",
                "--http-port", "0", "--bind", "127.0.0.1", "--port", str(port),
                "--duration", "1.5", "--output", str(out), "--power-source", "lipo-usb-disconnected",
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
                    deadline = time.monotonic()+1
                    while time.monotonic() < deadline:
                        for p in (configuration(), sample(), sender(attempts=1, accepted=1), timing(401, 1)):
                            payload = encoded_sample(p) if p["type"] == "sample" else json.dumps(p).encode()
                            tx.sendto(payload, ("127.0.0.1", port))
                        time.sleep(.05)
                stdout, stderr = process.communicate(timeout=6)
                self.assertEqual(process.returncode, 0, stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
            self.assertIn("Motion detected", stdout)
            self.assertIn("Motion stopped / settled", stdout)
            self.assertNotIn("[sample]", stdout)
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(summary["sessions"][0]["bursts"]["1"]["received_unique"], 1)
            self.assertTrue((out / "samples.csv").exists())
            self.assertIn("FINAL CAPTURE SUMMARY", (out / "capture.log").read_text())
            records = replay_records(out)
            self.assertGreater(len(records), 3)
            replay = DemoModel(mode="replay", clock=lambda: records[-1][0], console=False)
            for t, p in records:
                replay.on_packet(p, t)
            self.assertEqual(replay.snapshot()["state"], "settled")


if __name__ == "__main__":
    unittest.main()
