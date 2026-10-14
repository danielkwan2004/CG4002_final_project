"""Print UDP telemetry sent by wifi_battery_test.ino."""

import argparse
import socket
from datetime import datetime


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4210, help="UDP port (default: 4210)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("0.0.0.0", args.port))
        print(f"Listening for FireBeetle UDP telemetry on port {args.port}. Press Ctrl+C to stop.", flush=True)
        try:
            while True:
                packet, (sender_ip, sender_port) = sock.recvfrom(2048)
                timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
                message = packet.decode("utf-8", errors="replace").strip()
                print(f"[{timestamp}] {sender_ip}:{sender_port}  {message}", flush=True)
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
