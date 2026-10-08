# MQTT demo consumer: collect separate stream/dummy windows and publish results.
# Stroke/confidence values below are simulated; no trained model is called here.
import argparse
import json
import os
import time
import random
import threading
import uuid

import _bootstrap
from utilities.constants import (
    PacketType,
    CA_CERTS_PATH,
    HAPTIC_MIN_INTERVAL_SECONDS,
    HAPTIC_RESULTS_PER_TRIGGER,
    PORT_TLS,
    SENSOR_SOURCES,
    STROKES,
    TOPIC_HAPTICS,
    TOPIC_RESULTS,
    TOPIC_SENSOR,
    TRANSPORT_TLS,
)
from dotenv import load_dotenv
from utilities.logger_setup import get_logger
from utilities.mqtt_client import MQTTClientWrapper


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
# Windows contain one second of acquisition timestamps, not one second of
# MQTT arrivals. Zero delivery grace favours fast results over late samples.
SENSOR_WINDOW_MS = 1000
WINDOW_DELIVERY_GRACE_SECONDS = 0.0
sensor_windows = {source: {} for source in SENSOR_SOURCES.values()}
sensor_latest_start = {source: None for source in SENSOR_SOURCES.values()}
sensor_closed_until = {source: float("-inf") for source in SENSOR_SOURCES.values()}
# MQTT callbacks and the timer loop run on different threads. The condition
# protects window state; result_lock separately serialises result/haptic counters.
sensor_window_changed = threading.Condition()
sensor_session = None


def publish_ai_result(stroke, confidence, pairs):
    """Use the same AI result schema for streaming and keyboard demos."""
    global result_seq, results_since_haptic, haptic_seq, last_haptic_time
    source = pairs[-1]["source"]
    sensor_seq = pairs[-1]["sensor_seq"]
    sensor_session_id = pairs[-1]["session_id"]
    with result_lock:
        result_seq += 1
        result = {
            "type": PacketType.AI_RESULTS,
            "source": source,
            "timestamp": time.monotonic_ns() // 1_000_000,
            "session_id": result_session_id,
            "sensor_session_id": sensor_session_id,
            "result_seq": result_seq,
            "sensor_seq": sensor_seq,
            "stroke": stroke,
            "confidence": confidence,
            "sensor_sample_counts": {
                name: sum(packet.get(name) is not None for packet in pairs)
                for name in ("forearm", "paddle")
            },
            "complete_pairs": sum(
                packet.get("forearm") is not None and packet.get("paddle") is not None
                for packet in pairs
            ),
        }

        if not client.publish(TOPIC_RESULTS, result, qos=1):
            logger.info("Dropped AI result while MQTT is unavailable")
            return
        logger.info(f"Published AI result #{result_seq}: source = {source}, sensor_seq = {sensor_seq}, sample_packets = {len(pairs)}, stroke = {stroke}")

        # Dummy results never trigger haptics or advance the stream-result counter.
        if source == "dummy":
            return

        # Trigger after 10 streaming AI results, at least 10 seconds since last haptic.
        results_since_haptic += 1
        now = time.monotonic()
        if (results_since_haptic >= HAPTIC_RESULTS_PER_TRIGGER
                and now - last_haptic_time >= HAPTIC_MIN_INTERVAL_SECONDS):
            haptic_seq += 1
            client.publish(TOPIC_HAPTICS, {
                "type": PacketType.HAPTIC_CMD,
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
    """Publish each expired window once; late pairs cannot reopen it."""
    due = []
    with sensor_window_changed:
        now = time.monotonic()
        for source, windows in sensor_windows.items():
            for start, window in list(windows.items()):
                if now < window["deadline"]:
                    continue
                due.append(window["pairs"])
                del windows[start]
                sensor_closed_until[source] = max(sensor_closed_until[source], start + SENSOR_WINDOW_MS)
    for pairs in due:
        if pairs:
            publish_ai_result(random.choice(STROKES), round(random.uniform(0.75, 0.99), 2), pairs)


def handle_sensor_data(msg):
    global sensor_session
    try:
        sensor = json.loads(msg.payload.decode())
    except (ValueError, UnicodeDecodeError):
        logger.warning("Ignoring malformed sensor packet")
        return
    if (not isinstance(sensor, dict) or sensor.get("type") != PacketType.SENSOR_DATA
            or sensor.get("source") not in SENSOR_SOURCES.values()
            or not isinstance(sensor.get("session_id"), str) or not sensor["session_id"]
            or type(sensor.get("sensor_seq")) is not int or sensor["sensor_seq"] < 1
            or type(sensor.get("timestamp")) is not int):
        logger.warning("Ignoring sensor packet without a valid source/session/sequence/timestamp")
        return

    # Enforce the deadline on receipt too, even if the timer thread has not run.
    # A late tail must not reopen the completed dummy window as a second result.
    publish_sensor_window()
    with sensor_window_changed:
        if sensor_session != sensor["session_id"]:
            for source in sensor_windows:
                sensor_windows[source].clear()
                sensor_latest_start[source] = None
                sensor_closed_until[source] = float("-inf")
            sensor_session = sensor["session_id"]
        source = sensor["source"]
        timestamp = sensor["timestamp"]
        if timestamp < sensor_closed_until[source]:
            # A very late tail cannot reopen a finished window as another inference.
            logger.debug("Discarding late %s pair %d from a closed acquisition window", source, sensor["sensor_seq"])
            return
        windows = sensor_windows[source]
        start = next((start for start in windows if start <= timestamp < start + SENSOR_WINDOW_MS), None)
        if start is None:
            previous = sensor_latest_start[source]
            if previous is not None and timestamp < previous:
                logger.debug("Discarding out-of-order pair before the current acquisition window")
                return
            if source == "stream" and previous is not None:
                # Preserve contiguous acquisition windows even when MQTT delivers a backlog.
                start = previous + ((timestamp - previous) // SENSOR_WINDOW_MS) * SENSOR_WINDOW_MS
            else:
                # Each keyboard burst lasts <= 1 second and keys cannot overlap.
                # Its first available pair anchors the window.
                start = timestamp
            sensor_latest_start[source] = start
            # Bound samples by acquisition timestamp, but schedule expiration
            # using this machine's monotonic clock. The clocks need not agree.
            windows[start] = {
                "pairs": [],
                "deadline": time.monotonic() + (start + SENSOR_WINDOW_MS - timestamp) / 1000
                            + WINDOW_DELIVERY_GRACE_SECONDS,
            }
        windows[start]["pairs"].append(sensor)
        sensor_window_changed.notify()


client.subscribe(TOPIC_SENSOR, callback=handle_sensor_data, qos=0)
client.enable_latency("ultra96")

try:
    client.loop_start()
    logger.info("Waiting for sensor data; one-second acquisition windows with %.0fms delivery allowance",
                WINDOW_DELIVERY_GRACE_SECONDS * 1000)
    while True:
        with sensor_window_changed:
            deadlines = [window["deadline"] for windows in sensor_windows.values() for window in windows.values()]
            timeout = min(0.5, max(0.0, min(deadlines) - time.monotonic())) if deadlines else 0.5
            sensor_window_changed.wait(timeout=timeout)
        publish_sensor_window()
except KeyboardInterrupt:
    logger.info("Interrupted - disconnecting from MQTT")
finally:
    client.loop_stop()
