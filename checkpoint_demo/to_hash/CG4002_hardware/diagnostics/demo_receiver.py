"""Local browser dashboard for the v3/v4 receiver. Standard library only."""

import argparse
import csv
import json
import math
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .wifi_receiver import FIELD_NAMES, Session, main as capture_main, parse_packet


class DemoModel:
    """One selected node, with device-ordered motion state and bounded UI history.

    The independent capture writer still records every node/boot/duplicate. A
    delayed packet from a retired boot cannot switch the display back to it.
    Silence is a connection warning, never a fabricated movement-end event.
    """

    def __init__(self, node=1, mode="live", clock=time.monotonic, console=True):
        self.node, self.mode, self.clock, self.console = node, mode, clock, console
        self.lock = threading.RLock()
        self.started = clock()
        self.directory = None
        self.metadata = {}
        self.session = None
        self.retired_boots = set()
        self.events = deque(maxlen=12)
        self.points = deque(maxlen=700)
        self.finished = False
        self.finished_at = None
        self.stale = False
        self.invalid_packets = 0
        self._reset_motion()

    def _reset_motion(self):
        self.motion = None
        self.motion_order = (-1, -1)
        self.motion_at = None
        self.burst = 0
        self.latest = None
        self.latest_at = None
        self.latest_seq = -1
        self.points.clear()

    def _event(self, text, now):
        self.events.appendleft(dict(seconds=max(0, now - self.started), text=text))
        if self.console:
            print(f"[{max(0, now - self.started):6.1f}s] {text}", flush=True)

    def on_start(self, metadata, directory, start):
        with self.lock:
            self.started = start
            self.metadata = metadata
            self.directory = str(directory) if directory else None
            self._event("Receiver ready. Power on/reset the node; keep it flat and still.", start)
            if directory and self.console:
                print(f"Evidence folder: {directory}", flush=True)

    def _set_motion(self, active, burst, order, now):
        if order <= self.motion_order:
            return
        changed = self.motion is not active or (active and burst != self.burst)
        previous = self.motion
        self.motion, self.burst = active, burst
        self.motion_order, self.motion_at = order, now
        if changed:
            if active:
                self._event(f"Motion detected - burst {burst}.", now)
            elif previous is True:
                self._event("Motion stopped / settled - device gate is idle.", now)
            else:
                self._event("Ready / settled - no active movement burst.", now)

    def on_packet(self, p, now):
        if p["node"] != self.node:
            return
        with self.lock:
            if p["boot"] in self.retired_boots:
                return
            if self.session is None or p["boot"] != self.session.boot:
                if self.session:
                    self.retired_boots.add(self.session.boot)
                    self._event("Node rebooted - starting a new session.", now)
                else:
                    self._event(f"Node {self.node} connected.", now)
                self.session = Session(self.node, p["boot"])
                self._reset_motion()
            s = self.session
            old_state = s.latest_state
            old_transport_failures = s.transport["failed"] if s.transport else (
                0 if s.capture_start_seq == 0 else None)
            old_queue_drops = s.txqueue["dropped"] if s.txqueue else (
                0 if s.capture_start_seq == 0 else None)
            s.ingest(p, now)
            if self.stale:
                self.stale = False
                self._event("Connection restored.", now)
            if old_state != s.latest_state:
                messages = {"CALIBRATING": "Calibrating - keep the sensor flat and still.",
                            "STREAMING": "Acquisition running. Ready for the demonstration.",
                            "FAULT": "Device reports a fault - check the hardware."}
                if s.latest_state in messages:
                    self._event(messages[s.latest_state], now)
            kind = p["type"]
            if kind == "sample":
                self._set_motion(True, p["burst_id"], (p["seq"], 1), now)
                if p["seq"] > self.latest_seq:
                    self.latest_seq, self.latest_at = p["seq"], now
                    gyro = [p[a + "_filtered_dps"] for a in ("gx", "gy", "gz")]
                    accel = [p[a + "_filtered_g"] for a in ("ax", "ay", "az")]
                    gyro_norm = math.sqrt(sum(x*x for x in gyro))
                    accel_deviation = abs(math.sqrt(sum(x*x for x in accel)) - 1)
                    self.latest = dict(gyro=gyro, accel=accel, gyro_norm=gyro_norm,
                                       accel_deviation=accel_deviation,
                                       saturated=bool(p["status_flags"] & 1))
                    point = dict(t=now-self.started, value=gyro_norm, burst=p["burst_id"])
                    # Downsample only the display, preserving peaks per 50 ms bin.
                    if (self.points and self.points[-1]["burst"] == p["burst_id"]
                            and int(point["t"] * 20) == int(self.points[-1]["t"] * 20)):
                        if point["value"] > self.points[-1]["value"]:
                            self.points[-1] = point
                    else:
                        self.points.append(point)
            elif kind == "burst":
                if s.capture_start_seq is not None and p["last_seq"] >= s.capture_start_seq:
                    closed_gate = p.get("gate_closed", p["closed"])
                    self._set_motion(not closed_gate, p["id"],
                                     (p["last_seq"], 2 if closed_gate else 1), now)
            elif kind == "timing":
                self._set_motion(bool(p["active_burst"]), p["active_burst"],
                                 (p["produced"] - 1, 3), now)
            elif (kind == "transport" and old_transport_failures is not None
                  and s.transport["failed"] > old_transport_failures):
                t = s.transport
                wording = "Send errors (retryable data is queued, not declared lost)" if t["v"] == 4 else "Send errors"
                self._event(f"{wording}: +{t['failed']-old_transport_failures} socket errors. "
                            f"Last errno {t['last_errno']}; Wi-Fi status {t['last_wifi']}.", now)
            elif (kind == "txqueue" and old_queue_drops is not None
                  and s.txqueue["dropped"] > old_queue_drops):
                self._event(f"Delivery warning: {s.txqueue['dropped']-old_queue_drops} sample(s) "
                            "could not be retained/delivered by the transmit queue.", now)

    def on_tick(self, now):
        with self.lock:
            if not self.session or self.finished:
                return
            grace = 8 if self.session.latest_state == "CALIBRATING" else 3
            stale = now - self.session.last_receive_s > grace
            if stale and not self.stale:
                self._event("Connection quiet - motion state is unknown, not 'stopped'.", now)
            self.stale = stale

    def on_invalid(self, error, now):
        with self.lock:
            self.invalid_packets += 1
            if self.invalid_packets <= 3:
                self._event(f"Unrecognized packet - check v3/v4 receiver/firmware compatibility: {error}", now)

    def on_finish(self, summary, now):
        with self.lock:
            self.finished, self.finished_at = True, now
            self._event("Replay complete." if self.mode == "replay" else "Capture stopped. Evidence saved.", now)

    def snapshot(self):
        with self.lock:
            now = self.finished_at if self.finished else self.clock()
            self.on_tick(now)
            s = self.session
            age = max(0, now-s.last_receive_s) if s else None
            sample_age = max(0, now-self.latest_at) if self.latest_at is not None else None
            motion_age = max(0, now-self.motion_at) if self.motion_at is not None else None
            if self.finished:
                state = "complete"
            elif not s:
                state = "waiting"
            elif self.stale:
                state = "disconnected"
            elif s.latest_state == "FAULT":
                state = "fault"
            elif s.latest_state in ("BOOT", "CALIBRATING"):
                state = "calibrating"
            elif self.motion is None or motion_age is None or motion_age > 3:
                state = "unknown"
            else:
                state = "moving" if self.motion else "settled"
            summary = s.summary() if s else None
            duplicates = sum(b.duplicates for b in s.bursts.values()) if s else 0
            return dict(mode=self.mode, node=self.node, state=state,
                        elapsed_s=max(0, now-self.started), packet_age_s=age,
                        sample_age_s=sample_age, latest=self.latest,
                        burst=self.burst, summary=summary, duplicates=duplicates,
                        invalid_packets=self.invalid_packets,
                        directory=self.directory, metadata=self.metadata,
                        events=list(self.events), points=list(self.points))


def make_server(model, port):
    assets = Path(__file__).with_name("demo_web")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            # Loopback only, no filesystem browsing, cross-origin API, or mutations.
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed:
                self.send_error(403)
                return
            path = self.path.split("?", 1)[0]
            if path == "/api/state":
                payload = json.dumps(model.snapshot(), allow_nan=False).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            else:
                files = {"/": ("index.html", "text/html"),
                         "/app.js": ("app.js", "text/javascript"),
                         "/style.css": ("style.css", "text/css")}
                if path not in files:
                    self.send_error(404)
                    return
                filename, content_type = files[path]
                payload = (assets / filename).read_bytes()
                content_type += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    # Unlike the stdlib HTTP default, do not permit competing listeners on Windows.
    class LocalServer(ThreadingHTTPServer):
        allow_reuse_address = False
        daemon_threads = True

    return LocalServer(("127.0.0.1", port), Handler)


def replay_records(directory):
    """Read-only playback of genuine capture records, not generated sensor data."""
    records = []
    with (directory / "samples.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            packet = parse_packet(",".join(row[k] for k in FIELD_NAMES).encode("ascii"))
            records.append((float(row["host_elapsed_s"]), packet))
    with (directory / "diagnostics.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if "packet" in row:
                packet = parse_packet(json.dumps(row["packet"]).encode("ascii"))
                records.append((float(row["host_elapsed_s"]), packet))
    if not records or any(not math.isfinite(t) or t < 0 for t, _ in records):
        raise ValueError("Replay needs valid timestamped v3/v4 capture records.")
    return sorted(records, key=lambda item: item[0])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        "Live mode also accepts every wifi_receiver.py option, including --power-source, "
        "--sender-ip, --output and --duration. Stop the old receiver first."))
    parser.add_argument("--http-port", type=int, default=8765)
    parser.add_argument("--node-id", type=int, default=1)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--replay", type=Path, help="read-only replay of a saved capture; clearly labeled")
    parser.add_argument("--speed", type=float, default=1, help="replay speed, default 1")
    args, capture_args = parser.parse_known_args(argv)
    if not 1 <= args.node_id <= 255 or not 0 <= args.http_port <= 65535:
        parser.error("node ID must be 1..255 and HTTP port 0..65535")
    if not math.isfinite(args.speed) or args.speed <= 0:
        parser.error("speed must be finite and positive")
    if args.replay and capture_args:
        parser.error("capture options do not apply to read-only replay")
    if not args.replay and args.speed != 1:
        parser.error("--speed applies only to replay")
    model = DemoModel(node=args.node_id, mode="replay" if args.replay else "live")
    server = None
    try:
        records = replay_records(args.replay) if args.replay else None
        server = make_server(model, args.http_port)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_port}"
        print(f"\nPickleViz {'REPLAY (not live)' if args.replay else 'LIVE DEMO'}\nDashboard: {url}", flush=True)
        print("Press Ctrl+C in this terminal to stop. Keep only one UDP receiver running.\n", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        if records is None:
            return capture_main(capture_args, observer=model, quiet=True)
        start = time.monotonic()
        model.clock = lambda: start + (time.monotonic() - start) * args.speed
        model.on_start(dict(replay_source=str(args.replay.resolve()), replay_speed=args.speed), None, start)
        first = records[0][0]
        for elapsed, packet in records:
            due = start + elapsed - first
            while model.clock() < due:
                time.sleep(min(0.03, (due - model.clock()) / args.speed))
            model.on_packet(packet, due)
        model.on_finish({}, model.clock())
        print("Replay complete; dashboard remains open until Ctrl+C.", flush=True)
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, KeyError, csv.Error) as error:
        print(f"Could not start/continue demo: {error}", flush=True)
        print("Check the capture path, and stop other receivers on UDP 4210 or dashboards on this HTTP port.", flush=True)
        return 1
    finally:
        if server:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
