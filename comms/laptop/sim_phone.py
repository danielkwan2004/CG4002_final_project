import argparse
import os

import _bootstrap
from utilities.constants import (
    CA_CERTS_PATH,
    PORT_WSS, 
    TOPIC_RESULTS, 
    TOPIC_SENSOR, 
    TRANSPORT_WSS
)
from dotenv import load_dotenv
from utilities.mqtt_client import MQTTClientWrapper
from utilities.logger_setup import DEFAULT_LOG_DIR, get_logger


load_dotenv()
USER_PHONE = os.getenv("USER_PHONE")
PW_PHONE = os.getenv("PW_PHONE")

parser = argparse.ArgumentParser()
parser.add_argument("-v", "--verbose", action="store_true")
args = parser.parse_args()

logger = get_logger("sim_phone", verbose=args.verbose, log_dir=DEFAULT_LOG_DIR / "sim_phone")

client = MQTTClientWrapper(
    client_id="sim_phone",
    port=PORT_WSS,
    transport=TRANSPORT_WSS,
    ca_certs=CA_CERTS_PATH,
    username=USER_PHONE,
    password=PW_PHONE,
    logger=logger
)

def handle_sensor_data(msg):
    logger.info(f"[trajectory calc] Received sensor data ({len(msg.payload)} bytes)")

def handle_ai_results(msg):
    logger.info(f"[AR overlay] Received AI results: {msg.payload.decode()}")

client.subscribe(TOPIC_SENSOR, callback=handle_sensor_data, qos=0)
client.subscribe(TOPIC_RESULTS, callback=handle_ai_results, qos=1)
client.loop_forever()
