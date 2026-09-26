import asyncio
import argparse
import json
import os
import sys
import time
import contextlib
import uuid

from ble_sensor_node import BLESensorNode
from constants import (
    PORT_TLS,
    TRANSPORT_TLS,
    TOPIC_SENSOR,
    TOPIC_HAPTICS,
    TOPIC_RELAY,
    PKT_DUMMY_BATCH,
    CA_CERTS_PATH,
    HAPTIC_MIN_INTERVAL_SECONDS,
)
from dotenv import load_dotenv
from dummy_sensor_node import DummySensorNode
from logger_setup import get_logger
from mqtt_client import MQTTClientWrapper
from synchroniser import Synchroniser, paired_sensor_packet


load_dotenv()
USER_LAPTOP_CLI = os.getenv("USER_LAPTOP_CLI")
PW_LAPTOP_CLI = os.getenv("PW_LAPTOP_CLI")

async def publisher_task(output_queue: asyncio.Queue, mqtt_client: MQTTClientWrapper, logger, metrics):
    while True:
        paired_sample = await output_queue.get()
        mqtt_client.publish(TOPIC_SENSOR, paired_sample, qos=0)
        metrics["mqtt_bytes"] += len(json.dumps(paired_sample).encode())
        # logger.debug(f"Published synchronised sample sequence = {paired_sample['sequence']}")

async def stream_stats_task(nodes, sync, metrics, logger, interval: float = 5.0):
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
        logger.debug(f"[SYNC STATS] {stats}")
        previous_mqtt, started = mqtt_bytes, now

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


async def keyboard_task(nodes, replies, mqtt_client, logger, packets_per_key=5):
    """Send a complete paired batch per key; discard incomplete batches."""
    sequence = 0
    session = uuid.uuid4().hex
    logger.info("Waiting for both FireBeetle handshakes...")
    await asyncio.gather(*(node.ready.wait() for node in nodes))
    logger.info("Keyboard relay ready (press any key to start; Ctrl-C to stop)")
    loop = asyncio.get_running_loop()
    keys = asyncio.Queue()
    fd = sys.stdin.fileno()
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
                # Printable ASCII demo keys; skip Enter and control bytes.
                if not 32 <= data[0] <= 126:
                    continue
                key = data.decode("ascii")
                if not all(node.ready.is_set() and node.client.is_connected for node in nodes):
                    logger.warning("Key skipped: both FireBeetles must be ready")
                    continue
                batch = []
                batch_id = uuid.uuid4().hex
                logger.info(f"[DUMMY] key = {key!r}: collecting {packets_per_key} pairs")
                for index in range(packets_per_key):
                    sequence += 1
                    sent = await asyncio.gather(*(node.send_dummy(key, sequence) for node in nodes))
                    if not all(sent):
                        logger.warning("[DUMMY] Incomplete send; entire keypress batch discarded")
                        break
                    pair = {}
                    deadline = loop.time() + 3.0
                    try:
                        while len(pair) < len(nodes):
                            node_id, reply = await asyncio.wait_for(replies.get(), max(0, deadline - loop.time()))
                            if reply.get("sequence") == sequence:
                                pair[node_id] = reply
                    except asyncio.TimeoutError:
                        logger.warning("[DUMMY] Missing reply; entire keypress batch discarded")
                        break
                    batch.append(paired_sensor_packet(pair["forearm"], pair["paddle"], sequence, session))
                    logger.debug(f"[DUMMY] Pair {index + 1}/{packets_per_key} received")
                if len(batch) != packets_per_key:
                    continue
                for node in nodes:
                    node.logger.info(f"Received {packets_per_key}/{packets_per_key} samples for key = {key!r}")
                mqtt_client.publish(TOPIC_RELAY, {
                    "type": PKT_DUMMY_BATCH, "session": session, "sequence": sequence,
                    "batch_id": batch_id, "sample_pairs": packets_per_key,
                    "key": key, "pairs": batch,
                }, qos=1)
                logger.info(f"[DUMMY] Complete batch ({packets_per_key} pairs) -> Ultra96")
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
        
async def main(verbose: bool, clock_resync: bool, keyboard_relay: bool, packets_per_key=5):
    logger = get_logger("laptop", verbose, log_dir="logs/laptop")

    main_loop = asyncio.get_running_loop()

    forearm_queue = asyncio.Queue()
    paddle_queue = asyncio.Queue()
    output_queue = asyncio.Queue()
    haptic_queue = asyncio.Queue(maxsize=1)

    replies = asyncio.Queue()
    forearm_node = BLESensorNode("forearm", clock_resync, forearm_queue, logger,
                                lambda reply: replies.put_nowait(("forearm", reply)),
                                streaming=not keyboard_relay)
    paddle_node = BLESensorNode("paddle", clock_resync, paddle_queue, logger,
                                lambda reply: replies.put_nowait(("paddle", reply)),
                                streaming=not keyboard_relay)
    sync = Synchroniser(forearm_queue, paddle_queue, output_queue, logger)

    mqtt_client = MQTTClientWrapper(
        client_id="laptop_cli",
        port=PORT_TLS,
        transport=TRANSPORT_TLS,
        ca_certs=CA_CERTS_PATH,
        username=USER_LAPTOP_CLI,
        password=PW_LAPTOP_CLI,
        logger=logger,
    )
    mqtt_client.loop_start()  # runs on its own background thread

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

    mqtt_client.subscribe(TOPIC_HAPTICS, callback=handle_haptic_command, qos=1)

    tasks = [asyncio.create_task(paddle_node.run()), asyncio.create_task(forearm_node.run())]
    tasks.append(asyncio.create_task(haptic_worker(haptic_queue, forearm_node, logger)))
    if keyboard_relay:
        logger.info("KEYBOARD MODE: keyboard only; connecting both FireBeetles, continuous stream disabled")
        tasks.append(asyncio.create_task(keyboard_task((forearm_node, paddle_node), replies, mqtt_client, logger, packets_per_key)))
    else:
        logger.info("STREAM MODE: continuous forearm + paddle streaming")
        metrics = {"mqtt_bytes": 0}
        tasks.extend([
            asyncio.create_task(sync.run()),
            asyncio.create_task(publisher_task(output_queue, mqtt_client, logger, metrics)),
            asyncio.create_task(stream_stats_task((forearm_node, paddle_node), sync, metrics, logger)),
        ])
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
    parser.add_argument("-k", "--keyboard-relay", action="store_true", help="Keyboard-only demo: pause IMU streaming and pair replies from both nodes")
    parser.add_argument("-p", "--packets-per-key", type=int, default=5,
                        help="Packets per FireBeetle per keypress, 1–1000 (default: 5)")
    args = parser.parse_args()
    if not 1 <= args.packets_per_key <= 1000:
        parser.error("--packets-per-key must be between 1 and 1000")
    if args.keyboard_relay and (os.name != "posix" or not sys.stdin.isatty()):
        parser.error("--keyboard-relay requires an interactive macOS/Linux terminal")

    try:
        asyncio.run(main(args.verbose, args.clock_resync, args.keyboard_relay, args.packets_per_key))
    except KeyboardInterrupt:
        print("\nInterrupted - Shutting down...")
