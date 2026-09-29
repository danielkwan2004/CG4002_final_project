import argparse
import csv
import socket
import sys
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


class NodeState:
    """Tracks one node's current/most-recent move segment for the live display."""

    def __init__(self):
        self.connected = False
        self.in_move = False
        self.move_count = 0
        self.last_seq = None
        self.last_packet_time = None
        self.move_start_time = None
        self.samples_this_move = 0
        self.missed_this_move = 0
        self.total_samples = 0


def format_live_status(packet):
    accel = (
        f"({float(packet['ax_filtered_g']):+.2f}, "
        f"{float(packet['ay_filtered_g']):+.2f}, "
        f"{float(packet['az_filtered_g']):+.2f}) g"
    )
    gyro = (
        f"({float(packet['gx_filtered_dps']):+6.1f}, "
        f"{float(packet['gy_filtered_dps']):+6.1f}, "
        f"{float(packet['gz_filtered_dps']):+6.1f}) deg/s"
    )
    return f"   accel={accel}   gyro={gyro}"


def start_move(node_id, state, now):
    state.in_move = True
    state.move_count += 1
    state.move_start_time = now
    state.samples_this_move = 0
    state.missed_this_move = 0
    print(f"\n>> [Node {node_id}] Move #{state.move_count} started")


def end_move(node_id, state, end_time):
    state.in_move = False
    duration = end_time - state.move_start_time if state.move_start_time else 0.0
    rate = state.samples_this_move / duration if duration > 0 else 0.0
    loss_note = (
        "no packet loss"
        if state.missed_this_move == 0
        else f"{state.missed_this_move} sample(s) possibly lost in transit"
    )
    # Overwrite the live status line, then print the summary on its own line.
    print(
        f"\r<< [Node {node_id}] Move #{state.move_count} ended   "
        f"duration={duration:.2f}s  samples={state.samples_this_move}  "
        f"~{rate:.0f} Hz  {loss_note}".ljust(90)
    )


def main():
    parser = argparse.ArgumentParser(description="Live monitor for CG4002 forearm sensor telemetry")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=4210)
    parser.add_argument("--sender-ip", help="optionally accept packets only from this ESP32 IP")
    parser.add_argument(
        "--refresh-interval",
        type=float,
        default=0.15,
        help="seconds between live accel/gyro line updates while a move is active",
    )
    args = parser.parse_args()

    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    receiver.bind((args.bind, args.port))
    receiver.settimeout(0.05)  # lets us notice a move ending, not just starting

    nodes = {}
    last_refresh = {}
    received = 0
    started = time.monotonic()

    print("=" * 60)
    print(" CG4002 Forearm Sensor -- Live Telemetry Monitor")
    print("=" * 60)
    print(f"Listening on {args.bind}:{args.port} ...")

    try:
        while True:
            try:
                payload, address = receiver.recvfrom(512)
            except socket.timeout:
                now = time.monotonic()
                for node_id, state in nodes.items():
                    if state.in_move and now - state.last_packet_time > MOVE_SEGMENT_TIMEOUT_S:
                        end_move(node_id, state, state.last_packet_time)
                continue

            if args.sender_ip and address[0] != args.sender_ip:
                continue

            try:
                packet = parse_packet(payload)
            except (UnicodeDecodeError, ValueError) as error:
                print(f"\nInvalid packet from {address[0]}: {error}")
                continue

            node_id = int(packet["node_id"])
            sequence = int(packet["seq"])
            now = time.monotonic()
            received += 1

            state = nodes.setdefault(node_id, NodeState())
            if not state.connected:
                state.connected = True
                print(f"[Node {node_id}] connected ({address[0]})")

            if not state.in_move:
                start_move(node_id, state, now)
            elif now - state.last_packet_time > MOVE_SEGMENT_TIMEOUT_S:
                end_move(node_id, state, state.last_packet_time)
                start_move(node_id, state, now)
            elif state.last_seq is not None and sequence != state.last_seq + 1:
                state.missed_this_move += sequence - state.last_seq - 1

            state.last_seq = sequence
            state.last_packet_time = now
            state.samples_this_move += 1
            state.total_samples += 1

            if now - last_refresh.get(node_id, 0.0) >= args.refresh_interval:
                last_refresh[node_id] = now
                sys.stdout.write("\r" + format_live_status(packet).ljust(90))
                sys.stdout.flush()
    except KeyboardInterrupt:
        elapsed = time.monotonic() - started
        rate = received / elapsed if elapsed > 0 else 0
        print("\n" + "=" * 60)
        print(f"Session summary: {received} packets in {elapsed:.1f}s (~{rate:.0f} Hz average)")
        for node_id, state in nodes.items():
            print(f"  Node {node_id}: {state.move_count} move(s), {state.total_samples} samples")
        print("=" * 60)


if __name__ == "__main__":
    main()
