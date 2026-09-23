import asyncio
import argparse
import json
import os

from ble_sensor_node import BLESensorNode
from constants import (
    PORT_TLS,
    TRANSPORT_TLS,
    TOPIC_SENSOR,
    TOPIC_HAPTICS,
    CA_CERTS_PATH,
    HAPTIC_MIN_INTERVAL_SECONDS,
)
from dotenv import load_dotenv
from dummy_sensor_node import DummySensorNode
from logger_setup import get_logger
from mqtt_client import MQTTClientWrapper
from synchroniser import Synchroniser


load_dotenv()
USER_LAPTOP_CLI = os.getenv("USER_LAPTOP_CLI")
PW_LAPTOP_CLI = os.getenv("PW_LAPTOP_CLI")

async def publisher_task(output_queue: asyncio.Queue, mqtt_client: MQTTClientWrapper, logger):
    while True:
        paired_sample = await output_queue.get()
        mqtt_client.publish(TOPIC_SENSOR, paired_sample, qos=0)
        logger.debug(f"Published synchronised sample ts={paired_sample['timestamp']}")

async def stats_task(sync: Synchroniser, logger, interval: float = 5.0):
    while True:
        await asyncio.sleep(interval)
        logger.info(f"[SYNC STATS] {sync.stats()}")

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
        
async def main(verbose: bool, clock_resync: bool):
    logger = get_logger("laptop", verbose, log_dir="logs/laptop")

    main_loop = asyncio.get_running_loop()

    forearm_queue = asyncio.Queue()
    paddle_queue = asyncio.Queue()
    output_queue = asyncio.Queue()
    haptic_queue = asyncio.Queue(maxsize=1)

    forearm_node = BLESensorNode("forearm", forearm_queue, logger)
    paddle_node = BLESensorNode("paddle", paddle_queue, logger)
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
            haptic_json = json.dumps(payload, separators=(",", ":"))
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

    tasks = [
        asyncio.create_task(forearm_node.run()),
        asyncio.create_task(paddle_node.run()),
        asyncio.create_task(sync.run()),
        asyncio.create_task(publisher_task(output_queue, mqtt_client, logger)),
        asyncio.create_task(stats_task(sync, logger)),
        asyncio.create_task(haptic_worker(haptic_queue, forearm_node, logger)),
    ]
    try:
        await asyncio.gather(*tasks)
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
    args = parser.parse_args()

    try:
        asyncio.run(main(args.verbose))
    except KeyboardInterrupt:
        print("\nInterrupted - Shutting down...")
