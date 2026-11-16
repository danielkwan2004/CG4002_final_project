"""Send 200 simulated paired IMU samples per capture, without BLE hardware."""
import argparse
import asyncio
import math
import os
import time
import uuid

import _bootstrap
from dummy_sensor_node import DummySensorNode
from synchroniser import paired_sensor_packet
from utilities.constants import TOPIC_RESULTS, TOPIC_SENSOR
from utilities.logger_setup import DEFAULT_LOG_DIR, get_logger
from utilities.mqtt_client import MQTTClientWrapper


async def send_capture(nodes, client, session_id, sequence):
    """Pace one second of synthetic acquisition data on a shared 200 Hz clock."""
    started = time.monotonic()
    timestamp_ms = int(started * 1000)
    sent = 0
    for index in range(200):
        await asyncio.sleep(max(0, started + index * 0.005 - time.monotonic()))
        samples = [node._generate_packet() for node in nodes]
        # Both virtual sensors share an exact simulated acquisition clock.
        for sample in samples:
            for field in ("timestamp", "raw_timestamp", "common_timestamp"):
                sample[field] = timestamp_ms + index * 5
        sequence += 1
        packet = paired_sensor_packet(*samples, sequence, session_id)
        sent += bool(client.publish(TOPIC_SENSOR, packet, qos=0))
    return sequence, sent


async def main(interval, verbose):
    logger = get_logger("dummy_sender", verbose, log_dir=DEFAULT_LOG_DIR / "laptop")
    nodes = [DummySensorNode(name, asyncio.Queue(), logger)
             for name in ("forearm", "paddle")]
    session_id = uuid.uuid4().hex
    client = MQTTClientWrapper(
        client_id="dummy_sender_" + session_id[:8],
        username=os.getenv("USER_LAPTOP_CLI"),
        password=os.getenv("PW_LAPTOP_CLI"),
        logger=logger,
    )
    client.subscribe(TOPIC_RESULTS,
                     callback=lambda msg: logger.info("AI result: %s", msg.payload.decode()),
                     qos=1)
    client.loop_start()
    sequence = 0
    try:
        logger.info("Sending 200 paired dummy samples every %.2fs; Ctrl-C stops", interval)
        while True:
            while not client.client.is_connected():
                await asyncio.sleep(0.1)
            started = time.monotonic()
            sequence, sent = await send_capture(nodes, client, session_id, sequence)
            logger.info("Capture: %d/200 pairs accepted for MQTT publishing", sent)
            await asyncio.sleep(max(0, started + interval - time.monotonic()))
    finally:
        client.loop_stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=2.0,
                        help="Seconds between capture starts (default: 2; minimum: 2)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    if not math.isfinite(args.interval) or args.interval < 2:
        parser.error("--interval must be finite and at least 2 seconds")
    try:
        asyncio.run(main(args.interval, args.verbose))
    except KeyboardInterrupt:
        print("\nStopped dummy sender")
