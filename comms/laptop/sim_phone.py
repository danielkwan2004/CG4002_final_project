import argparse
from mqtt_client import MQTTClientWrapper
from logger_setup import get_logger
from constants import PORT_WSS, TOPIC_SENSOR, TOPIC_RESULTS, TRANSPORT_WSS, CA_CERTS_PATH

parser = argparse.ArgumentParser()
parser.add_argument("-v", "--verbose", action="store_true")
args = parser.parse_args()

logger = get_logger("sim_phone", verbose=args.verbose)

client = MQTTClientWrapper(
    client_id="sim_phone",
    port=PORT_WSS,
    transport=TRANSPORT_WSS,
    ca_certs=CA_CERTS_PATH,
    logger=logger
)

def handle_sensor_data(msg):
    logger.info(f"[trajectory calc] Received sensor data ({len(msg.payload)} bytes)")

def handle_ai_results(msg):
    logger.info(f"[AR overlay] Received AI results: {msg.payload.decode()}")

client.subscribe(TOPIC_SENSOR, callback=handle_sensor_data, qos=0)
client.subscribe(TOPIC_RESULTS, callback=handle_ai_results, qos=1)
client.loop_forever()