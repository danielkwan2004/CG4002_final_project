import argparse
import json
import os
import time
import random
import threading
import uuid

from constants import (
    CA_CERTS_PATH,
    HAPTIC_MIN_INTERVAL_SECONDS,
    HAPTIC_RESULTS_PER_TRIGGER,
    PKT_AI_RESULTS,
    PKT_DUMMY_BATCH,
    PKT_HAPTIC_CMD,
    PKT_SENSOR_DATA,
    PORT_TLS,
    STROKES,
    TOPIC_HAPTICS,
    TOPIC_RESULTS,
    TOPIC_SENSOR,
    TOPIC_RELAY,
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

result_seq = 0
result_session_id = uuid.uuid4().hex
result_lock = threading.Lock()
haptic_seq = 0
results_since_haptic = 0
last_haptic_time = float("-inf")
sensor_window = []
sensor_window_lock = threading.Lock()
sensor_window_changed = threading.Condition(sensor_window_lock)
sensor_deadline = None
sensor_last_sequence = 0
relay_session = None
relay_last_sequence = -1


def publish_ai_result(stroke, confidence, pairs):
    """Use the same AI result schema for streaming and keyboard demos."""
    global result_seq, results_since_haptic, haptic_seq, last_haptic_time
    sensor_seq = pairs[-1]["sensor_seq"]
    sensor_session_id = pairs[-1]["session_id"]
    with result_lock:
        result_seq += 1
        result = {
            "type": PKT_AI_RESULTS,
            "timestamp": time.monotonic_ns() // 1_000_000,
            "session_id": result_session_id,
            "sensor_session_id": sensor_session_id,
            "sensor_seqs": [pair["sensor_seq"] for pair in pairs],
            "result_seq": result_seq,
            "sensor_seq": sensor_seq,
            "stroke": stroke,
            "confidence": confidence,
            "sample_pairs": len(pairs),
        }

        client.publish(TOPIC_RESULTS, result, qos=1)
        logger.info(f"Published AI result #{result_seq}: sensor_seq = {sensor_seq}, stroke = {stroke}")

        # trigger haptic packet after 10 AI results, at least 10 seconds since last haptic
        results_since_haptic += 1
        now = time.monotonic()
        if (results_since_haptic >= HAPTIC_RESULTS_PER_TRIGGER
                and now - last_haptic_time >= HAPTIC_MIN_INTERVAL_SECONDS):
            haptic_seq += 1
            client.publish(TOPIC_HAPTICS, {
                "type": PKT_HAPTIC_CMD,
                "timestamp": time.monotonic_ns() // 1_000_000,
                "session_id": result_session_id,
                "sensor_session_id": sensor_session_id,
                "haptic_seq": haptic_seq,
                "result_seq": result_seq,
                "sensor_seq": sensor_seq,
                "pattern": "double_pulse",
            }, qos=1)
            results_since_haptic = 0
            last_haptic_time = now
            logger.info(f"Published haptic #{haptic_seq}: result_seq = {result_seq}, sensor_seq = {sensor_seq}")


def publish_sensor_window():
    """Drain a due window; an empty interval disarms the timer."""
    global sensor_deadline
    with sensor_window_lock:
        now = time.monotonic()
        if sensor_deadline is None or now < sensor_deadline:
            return
        
        count = len(sensor_window)
        pairs = list(sensor_window)
        sensor_window.clear()
        sensor_deadline = max(sensor_deadline + 1.0, now) if count else None

    if count:
        publish_ai_result(random.choice(STROKES), round(random.uniform(0.75, 0.99), 2),
                          pairs)


def handle_sensor_data(msg):
    global sensor_last_sequence, sensor_deadline

    try:
        sensor = json.loads(msg.payload.decode())
    except (ValueError, UnicodeDecodeError):
        logger.warning("Ignoring malformed sensor packet")
        return
    if (not isinstance(sensor, dict) or sensor.get("type") != PKT_SENSOR_DATA
            or not isinstance(sensor.get("session_id"), str) or not sensor["session_id"]
            or type(sensor.get("sensor_seq")) is not int or sensor["sensor_seq"] < 1):
        logger.warning("Ignoring sensor packet without a valid sensor_seq; update laptop")
        return

    logger.debug(
        f"Received sensor packet #{sensor['sensor_seq']}: ({len(msg.payload)} bytes)"
    )

    with sensor_window_changed:
        if sensor_window and sensor_window[-1]["session_id"] != sensor["session_id"]:
            logger.warning("Laptop session changed; discarding partial sensor window")
            sensor_window.clear()
            sensor_deadline = None
        sensor_window.append(sensor)
        sensor_last_sequence = sensor["sensor_seq"]
        if sensor_deadline is None:
            sensor_deadline = time.monotonic() + 1.0
            sensor_window_changed.notify()



def handle_dummy_relay(msg):
    """One complete keypress batch produces one simulated AI result."""
    global relay_session, relay_last_sequence

    try:
        relay = json.loads(msg.payload.decode())
    except (ValueError, UnicodeDecodeError):
        logger.warning("Ignoring malformed dummy relay")
        return
    
    if (not isinstance(relay, dict) or relay.get("type") != PKT_DUMMY_BATCH
            or not isinstance(relay.get("pairs"), list)
            or not 1 <= len(relay["pairs"]) <= 1000
            or relay.get("sample_pairs") != len(relay["pairs"])
            or not isinstance(relay.get("session"), str)
            or not isinstance(relay.get("sequence"), int)):
        logger.warning("Ignoring unpaired dummy packet; update the laptop pipeline")
        return
    
    pairs = relay["pairs"]
    logger.info(f"Received dummy relay packet: {len(pairs)} sample pairs")

    for index, pair in enumerate(pairs):
        expected = relay["sequence"] - len(pairs) + 1 + index
        if (not isinstance(pair, dict) or pair.get("type") != PKT_SENSOR_DATA
                or pair.get("session_id") != relay["session"]
                or type(pair.get("sensor_seq")) is not int
                or pair["sensor_seq"] != expected
                or pair.get("forearm_seq") != expected
                or pair.get("paddle_seq") != expected
                or not isinstance(pair.get("timestamp"), (int, float))
                or any(not isinstance(pair.get(node), dict)
                       or any(not isinstance(pair[node].get(field), dict)
                              or set(pair[node][field]) != {"x", "y", "z"}
                              for field in ("acceleration", "gyroscope"))
                       for node in ("forearm", "paddle"))):
            logger.warning("Ignoring incomplete or mismatched keypress batch")
            return
        
    if relay_session != relay["session"]:
        relay_session = relay["session"]
        relay_last_sequence = -1

    if relay["sequence"] <= relay_last_sequence:
        return  # QoS 1 may redeliver an already collected pair.
    
    relay_last_sequence = relay["sequence"]

    logger.debug(
        f"Keyboard batch={relay.get('batch_id')} key={relay.get('key')!r} "
        f"sequences={pairs[0]['forearm_seq']}..{relay['sequence']}"
    )
    publish_ai_result(random.choice(STROKES), round(random.uniform(0.75, 0.99), 2),
                      pairs)


client.subscribe(TOPIC_SENSOR, callback=handle_sensor_data, qos=0)
client.subscribe(TOPIC_RELAY, callback=handle_dummy_relay, qos=1)

try:
    client.loop_start()
    logger.info("Waiting for sensor data; first sample starts a 1-second AI window")
    while True:
        with sensor_window_changed:
            if sensor_deadline is None:
                sensor_window_changed.wait(timeout=0.5)
            else:
                timeout = min(0.5, max(0.0, sensor_deadline - time.monotonic()))
                sensor_window_changed.wait(timeout=timeout)
        publish_sensor_window()
except KeyboardInterrupt:
    logger.info("Interrupted - disconnecting from MQTT")
finally:
    client.loop_stop()
