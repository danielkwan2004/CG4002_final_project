import time
import argparse
from mqtt_client import MQTTClientWrapper
from logger_setup import get_logger
from constants import PORT_TLS, TOPIC_SENSOR, TOPIC_RESULTS, TOPIC_HAPTICS, TRANSPORT_TLS, CA_CERTS_PATH

parser = argparse.ArgumentParser()
parser.add_argument("-v", "--verbose", action="store_true")
args = parser.parse_args()

logger = get_logger("sim_ultra96", verbose=args.verbose)

client = MQTTClientWrapper(
    client_id="sim_ultra96",
    port=PORT_TLS,
    transport=TRANSPORT_TLS,
    ca_certs=CA_CERTS_PATH,
    lwt_topic="sys/ultra96/status",
    lwt_payload="offline",
    logger=logger
)

packet_count = 0

def handle_sensor_data(msg):
    global packet_count
    packet_count += 1
    logger.info(f"Received sensor packet #{packet_count}: ({len(msg.payload)} bytes)")

    time.sleep(0.1)  # simulate processing delay

    client.publish(TOPIC_RESULTS, {
        "type": "ai_results",
        "timestamp": int(time.time() * 1000),
        "stroke": "forehand",
        "confidence": 0.93
    }, qos=1)

    if packet_count % 10 == 0:
        client.publish(TOPIC_HAPTICS, {
            "type": "haptic_cmd",
            "timestamp": int(time.time() * 1000),
            "pattern": "double_pulse"
        }, qos=1)

client.subscribe(TOPIC_SENSOR, callback=handle_sensor_data, qos=0)
client.loop_forever()