import argparse
import os
import time

from constants import (
    CA_CERTS_PATH,
    HAPTIC_MIN_INTERVAL_SECONDS,
    PKT_AI_RESULTS,
    PKT_HAPTIC_CMD,
    PORT_TLS,
    TOPIC_HAPTICS,
    TOPIC_RESULTS,
    TOPIC_SENSOR,
    TRANSPORT_TLS,
)
from dotenv import load_dotenv
from logger_setup import get_logger
from mqtt_client import MQTTClientWrapper


load_dotenv()
USER_ULTRA96 = os.getenv("USER_ULTRA96")
PW_ULTRA96 = os.getenv("PW_ULTRA96")

parser = argparse.ArgumentParser()
parser.add_argument("-v", "--verbose", action="store_true")
args = parser.parse_args()

logger = get_logger("ultra96", verbose=args.verbose)

client = MQTTClientWrapper(
    client_id="ultra96",
    port=PORT_TLS,
    transport=TRANSPORT_TLS,
    ca_certs=CA_CERTS_PATH,
    username=USER_ULTRA96,
    password=PW_ULTRA96,
    lwt_topic="sys/ultra96/status",
    lwt_payload="offline",
    logger=logger,
)

packet_count = 0
haptic_count = 0
last_haptic_time = float("-inf")


def handle_sensor_data(msg):
    global packet_count, haptic_count, last_haptic_time

    packet_count += 1
    logger.info(
        f"Received sensor packet #{packet_count}: ({len(msg.payload)} bytes)"
    )

    generated_timestamp = time.monotonic_ns() / 1e6
    client.publish(
        TOPIC_RESULTS,
        {
            "type": PKT_AI_RESULTS,
            "timestamp": generated_timestamp,
            "packet_seq": packet_count,
            "stroke": "forehand",
            "confidence": 0.93,
        },
        qos=1,
    )

    now = time.monotonic_ns() / 1e6
    haptic_due = now - last_haptic_time >= HAPTIC_MIN_INTERVAL_SECONDS
    if packet_count % 10 == 0 and haptic_due:
        haptic_count += 1
        client.publish(
            TOPIC_HAPTICS,
            {
                "type": PKT_HAPTIC_CMD,
                "haptic_seq": haptic_count,
                "timestamp": now,
                "pattern": "double_pulse",
            },
            qos=1,
        )
        last_haptic_time = now
        logger.info(f"Published haptic packet #{haptic_count}")


client.subscribe(TOPIC_SENSOR, callback=handle_sensor_data, qos=0)

try:
    client.loop_forever()
except KeyboardInterrupt:
    logger.info("Interrupted - disconnecting from MQTT")
finally:
    client.disconnect()
