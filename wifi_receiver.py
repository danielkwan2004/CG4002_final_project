import argparse
import csv
import socket
import time

FIELD_NAMES = [
    "version",
    "node_id",
    "seq",
    "timestamp_us",
    "ax_raw",
    "ay_raw",
    "az_raw",
    "gx_raw",
    "gy_raw",
    "gz_raw",
    "ax_g",
    "ay_g",
    "az_g",
    "gx_dps",
    "gy_dps",
    "gz_dps",
    "ax_filtered_g",
    "ay_filtered_g",
    "az_filtered_g",
    "gx_filtered_dps",
    "gy_filtered_dps",
    "gz_filtered_dps",
    "status_flags",
]

# Firmware now only streams while its MoveDetector considers a move active,
# so a receive gap longer than this is an idle period between moves, not
# packet loss -- it just marks the start of a new burst. Kept close to the
# firmware's own MOVE_MIN_QUIET_MS (150ms) so two real moves separated by
# just that debounce window aren't misreported as a dropped-packet GAP.
MOVE_SEGMENT_TIMEOUT_S = 0.2


def parse_packet(payload):
    values = next(csv.reader([payload.decode("ascii").strip()]))
    if len(values) != len(FIELD_NAMES):
        raise ValueError(f"expected {len(FIELD_NAMES)} fields, got {len(values)}")
    return dict(zip(FIELD_NAMES, values))


def main():
    parser = argparse.ArgumentParser(description="Receive temporary ESP32 UDP telemetry")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=4210)
    parser.add_argument("--sender-ip", help="optionally accept packets only from this ESP32 IP")
    parser.add_argument(
        "--print-interval",
        type=float,
        default=0.5,
        help="seconds between printed lines (every packet is still counted for gap detection)",
    )
    args = parser.parse_args()

    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    receiver.bind((args.bind, args.port))
    receiver.settimeout(0.05)  # lets us notice a move ending, not just starting

    last_seq = {}
    last_packet_time = {}
    in_move = {}
    received = 0
    started = time.monotonic()
    last_print_time = 0.0

    print(f"Listening for UDP telemetry on {args.bind}:{args.port}")

    try:
        while True:
            try:
                payload, address = receiver.recvfrom(512)
            except socket.timeout:
                now = time.monotonic()
                for node_id, was_active in list(in_move.items()):
                    if was_active and now - last_packet_time[node_id] > MOVE_SEGMENT_TIMEOUT_S:
                        in_move[node_id] = False
                        print(f"=== node={node_id} move ended (idle) ===")
                continue

            if args.sender_ip and address[0] != args.sender_ip:
                continue
            try:
                packet = parse_packet(payload)
                node_id = int(packet["node_id"])
                sequence = int(packet["seq"])
                now = time.monotonic()

                starting_new_move = not in_move.get(node_id, False) or (
                    node_id in last_packet_time
                    and now - last_packet_time[node_id] > MOVE_SEGMENT_TIMEOUT_S
                )
                if starting_new_move:
                    in_move[node_id] = True
                    print(f"=== node={node_id} move started seq={sequence} ===")

                previous = last_seq.get(node_id)
                gap = ""
                if not starting_new_move and previous is not None and sequence != previous + 1:
                    gap = f" GAP(expected={previous + 1})"
                last_seq[node_id] = sequence
                last_packet_time[node_id] = now
                received += 1

                # Every packet is counted above so gap detection stays accurate;
                # only the console line itself is throttled for readability.
                # A real gap always prints immediately so packet loss isn't hidden.
                if gap or now - last_print_time >= args.print_interval:
                    last_print_time = now
                    print(
                        f"node={node_id} seq={sequence} "
                        f"accel=({packet['ax_filtered_g']},"
                        f"{packet['ay_filtered_g']},{packet['az_filtered_g']})g "
                        f"gyro=({packet['gx_filtered_dps']},"
                        f"{packet['gy_filtered_dps']},{packet['gz_filtered_dps']})dps "
                        f"status={packet['status_flags']} "
                        f"from={address[0]}{gap}"
                    )
            except (UnicodeDecodeError, ValueError) as error:
                print(f"Invalid packet from {address[0]}: {error}")
    except KeyboardInterrupt:
        elapsed = time.monotonic() - started
        rate = received / elapsed if elapsed > 0 else 0
        print(f"\nReceived {received} packets in {elapsed:.1f}s ({rate:.1f} packets/s)")


if __name__ == "__main__":
    main()
