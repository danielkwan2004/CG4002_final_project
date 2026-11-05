# Laptop entry point: BLE nodes -> per-node queues -> timestamp pairing -> MQTT.
# Keyboard captures share that path; haptics travel back from MQTT to the forearm.
import asyncio
import argparse
import json
import os
import sys
import time
import contextlib

from ble_sensor_node import BLESensorNode
import _bootstrap
from utilities.constants import (
    PORT_TLS,
    TRANSPORT_TLS,
    TOPIC_SENSOR,
    TOPIC_HAPTICS,
    TOPIC_HANDEDNESS,
    CA_CERTS_PATH,
    HAPTIC_MIN_INTERVAL_SECONDS,
)
from dotenv import load_dotenv
from utilities.logger_setup import DEFAULT_LOG_DIR, get_logger
from utilities.mqtt_client import MQTTClientWrapper
from synchroniser import Synchroniser


load_dotenv()
USER_LAPTOP_CLI = os.getenv("USER_LAPTOP_CLI")
PW_LAPTOP_CLI = os.getenv("PW_LAPTOP_CLI")

# Give both BLE writes time to arrive before their common sampling start.
# Acquisition still lasts one second; this is only the scheduling lead.
CAPTURE_LEAD_MS = 200

# Paired and single-sensor samples are published. The session and sequence fields let receivers
# distinguish laptop restarts and trace an AI result back to its final input pair.
async def publisher_task(output_queue: asyncio.Queue, mqtt_client: MQTTClientWrapper, logger, metrics, sync):
    while True:
        paired_sample = await output_queue.get()
        if not sync.active or paired_sample["session_id"] != sync.session_id:
            continue
        if not mqtt_client.publish(TOPIC_SENSOR, paired_sample, qos=0):
            continue  # Drop live samples while offline; never replay an old stream.
        metrics["mqtt_bytes"] += len(json.dumps(paired_sample).encode())
        logger.debug("[SENSOR TX] source=%s sensor_seq=%s forearm_seq=%s paddle_seq=%s timestamp_ms=%s",
                     paired_sample["source"], paired_sample["sensor_seq"], paired_sample["forearm_seq"],
                     paired_sample["paddle_seq"], paired_sample["timestamp"])

async def stream_stats_task(nodes, sync, metrics, logger, interval: float = 15.0):
    previous = {node.node_id: node.rx_bytes for node in nodes}
    previous_mqtt = metrics["mqtt_bytes"]
    started = time.monotonic()
    while True:
        await asyncio.sleep(interval)
        now = time.monotonic()
        elapsed = max(now - started, 0.001)
        rates = []
        for node in nodes:
            kbps = (node.rx_bytes - previous[node.node_id]) * 8 / elapsed / 1000
            rates.append(f"{node.node_id} = {kbps:.2f} kbps")
            previous[node.node_id] = node.rx_bytes
        mqtt_bytes = metrics["mqtt_bytes"]
        mqtt_kbps = (mqtt_bytes - previous_mqtt) * 8 / elapsed / 1000
        stats = sync.stats()
        logger.info(f"Stream: {' | '.join(rates)} | MQTT TX = {mqtt_kbps:.2f} kbps | "
                    f"pairing = {stats['match_rate_percent']:.2f}% (cumulative)")
        logger.info(f"[SYNC STATS] {stats}")
        previous_mqtt, started = mqtt_bytes, now

# RTT probes use the laptop clock at both ends; they do not measure inference
# turnaround or phone rendering, and do not require device clock synchronisation.
async def latency_task(nodes, mqtt_client):
    while True:
        mqtt_client.send_latency_probes()
        await asyncio.gather(*(node.measure_latency() for node in nodes))
        await asyncio.sleep(10.0)


@contextlib.contextmanager
def raw_keyboard():
    if not sys.stdin.isatty():
        yield
        return
    import termios
    import tty
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


async def keyboard_task(nodes, logger, sync=None, mode="keyboard"):
    """Request a one-second burst through the ordinary decoder and publisher."""
    if sync is not None:
        logger.info("Session paused: press SPACE to start/stop after both sensors deliver fresh data; Ctrl-C exits")
    if mode in ("keyboard", "both"):
        logger.info("Printable keys request a one-second capture; SPACE is reserved in both mode")
    loop = asyncio.get_running_loop()
    keys = asyncio.Queue()
    fd = sys.stdin.fileno()
    busy_until = 0.0

    def read_key():
        data = os.read(fd, 1)
        keys.put_nowait(data)
        if not data:
            loop.remove_reader(fd)

    with raw_keyboard():
        loop.add_reader(fd, read_key)
        try:
            while True:
                data = await keys.get()
                if not data:
                    return
                if sync is not None and data == b" ":
                    if sync.active:
                        sync.stop_session()
                        logger.info("Session stopped: %s", sync.stats())
                    elif not all(node.ready.is_set() and node.client is not None
                                 and node.client.is_connected for node in nodes):
                        logger.warning("Start skipped: both FireBeetles must be connected and ready")
                    elif sync.start_session():
                        logger.info("Session started: %s", sync.session_id)
                    else:
                        logger.warning("Start skipped: both sensors need samples acquired within the last 2 seconds; move both and retry SPACE")
                    continue
                if mode == "stream" or (sync is not None and not sync.active):
                    continue
                if not 32 <= data[0] <= 126:
                    continue
                if loop.time() < busy_until:
                    logger.info("Key ignored: one-second capture already active")
                    continue
                available = [node for node in nodes if node.ready.is_set()
                             and node.client is not None and node.client.is_connected]
                if not available:
                    logger.warning("Key skipped: no FireBeetle is ready")
                    continue
                # Schedule both nodes against the same corrected laptop clock.
                # No key, session, sequence override or dummy payload is sent.
                start_ms = time.monotonic_ns() / 1e6 + CAPTURE_LEAD_MS
                busy_until = start_ms / 1000 + 1.1
                logger.info("Capture key handled: sampling starts in %dms and lasts 1000ms",
                            CAPTURE_LEAD_MS)
                sent = await asyncio.gather(*(node.send_capture(start_ms) for node in available))
                if all(sent):
                    logger.debug("One-second burst requested")
                else:
                    logger.warning("Capture write failed; received samples still enter the AI window")
        finally:
            loop.remove_reader(fd)


async def haptic_worker(haptic_queue: asyncio.Queue, forearm_node: BLESensorNode, logger):
    """Send at most one current haptic command per cooldown interval."""
    last_sent = 0.0
    while True:
        haptic_json = await haptic_queue.get()
        delay = HAPTIC_MIN_INTERVAL_SECONDS - (asyncio.get_running_loop().time() - last_sent)
        if delay > 0:
            await asyncio.sleep(delay)

        # A newer command may have arrived during the cooldown. Stale haptic
        # feedback is not useful, so send only the newest queued command.
        while True:
            try:
                haptic_json = haptic_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        if await forearm_node.send_haptic(haptic_json):
            last_sent = asyncio.get_running_loop().time()
        else:
            logger.debug("Dropped haptic command because the forearm write failed")
        
async def main(verbose: bool, clock_resync: bool, mode: str, readiness_gate: bool = True):
    logger = get_logger("laptop", verbose, log_dir=DEFAULT_LOG_DIR / "laptop")

    main_loop = asyncio.get_running_loop()

    forearm_queue = asyncio.Queue()
    paddle_queue = asyncio.Queue()
    output_queue = asyncio.Queue()
    haptic_queue = asyncio.Queue(maxsize=1)

    connection_lock = asyncio.Lock()
    forearm_node = BLESensorNode("forearm", clock_resync, forearm_queue, logger,
                                streaming=mode != "keyboard", connection_lock=connection_lock)
    paddle_node = BLESensorNode("paddle", clock_resync, paddle_queue, logger,
                                streaming=mode != "keyboard", connection_lock=connection_lock)
    gate_enabled = readiness_gate and mode != "keyboard"
    sync = Synchroniser(forearm_queue, paddle_queue, output_queue, logger,
                        readiness_gate=gate_enabled)

    mqtt_client = MQTTClientWrapper(
        client_id="laptop_cli",
        port=PORT_TLS,
        transport=TRANSPORT_TLS,
        ca_certs=CA_CERTS_PATH,
        username=USER_LAPTOP_CLI,
        password=PW_LAPTOP_CLI,
        logger=logger,
    )
    mqtt_client.enable_latency("laptop", targets=("laptop", "ultra96", "phone"))

    # Paho invokes this on its network thread. Queue updates must be scheduled
    # onto the asyncio thread that owns the BLE nodes and haptic worker.
    def handle_haptic_command(msg):
        try:
            payload = json.loads(msg.payload.decode())
            # Session/window metadata is for MQTT tracing; keep BLE commands
            # compact enough for the existing characteristic payload.
            haptic_json = json.dumps({k: payload[k] for k in
                ("type", "timestamp", "haptic_seq", "result_seq", "sensor_seq", "pattern")
                if k in payload}, separators=(",", ":"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning(f"Ignoring malformed haptic command: {exc}")
            return

        def enqueue_latest():
            if haptic_queue.full():
                haptic_queue.get_nowait()
                logger.debug("Replaced stale queued haptic command")
            haptic_queue.put_nowait(haptic_json)

        try:
            main_loop.call_soon_threadsafe(enqueue_latest)
        except RuntimeError:
            # The asyncio loop is already closing.
            logger.debug("Ignored haptic command during shutdown")

    def handle_handedness(msg):
        payload = json.loads(msg.payload.decode())
        logger.info(f"[HANDEDNESS]: {payload}")

    mqtt_client.subscribe(TOPIC_HAPTICS, callback=handle_haptic_command, qos=1)
    mqtt_client.subscribe(TOPIC_HANDEDNESS, callback=handle_handedness, qos=1)
    mqtt_client.loop_start()  # Initial connection and retries run in the background.

    tasks = [asyncio.create_task(paddle_node.run()), asyncio.create_task(forearm_node.run())]
    tasks.append(asyncio.create_task(haptic_worker(haptic_queue, forearm_node, logger)))
    tasks.append(asyncio.create_task(latency_task((forearm_node, paddle_node), mqtt_client)))
    logger.info(f"MODE: {mode}; clock resync {'enabled' if clock_resync else 'disabled'}")
    metrics = {"mqtt_bytes": 0}
    tasks.extend([
        asyncio.create_task(sync.run()),
        asyncio.create_task(publisher_task(output_queue, mqtt_client, logger, metrics, sync)),
        asyncio.create_task(stream_stats_task((forearm_node, paddle_node), sync, metrics, logger)),
    ])
    if gate_enabled or mode in ("keyboard", "both"):
        tasks.append(asyncio.create_task(keyboard_task(
            (forearm_node, paddle_node), logger, sync if gate_enabled else None, mode)))
    try:
        # Shield children so Ctrl-C does not cancel BLE cleanup twice.
        await asyncio.shield(asyncio.gather(*tasks, return_exceptions=True))
    except asyncio.CancelledError:
        logger.info("Shutting down, cancelling tasks...")
    finally:
        # Stop the MQTT callback thread before cancelling the haptic worker so
        # no new commands can be scheduled while BLE is disconnecting.
        mqtt_client.loop_stop()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-c", "--clock-resync", action="store_false", help="Disable clock resync")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("-m", "--mode", choices=("stream", "keyboard", "both"), default="stream")
    modes.add_argument("-k", "--keyboard", dest="mode", action="store_const",
                       const="keyboard", help="Alias for --mode keyboard")
    parser.add_argument("--no-readiness-gate", action="store_true",
                        help="Publish immediately without SPACE start/stop (also permits headless stream mode)")
    args = parser.parse_args()
    if (args.mode in ("keyboard", "both") or not args.no_readiness_gate) and (os.name != "posix" or not sys.stdin.isatty()):
        parser.error("Readiness gate and keyboard modes require an interactive macOS/Linux terminal; use --no-readiness-gate for headless stream mode")

    try:
        asyncio.run(main(args.verbose, args.clock_resync, args.mode, not args.no_readiness_gate))
    except KeyboardInterrupt:
        print("\nInterrupted - Shutting down...")
