
#!/usr/bin/env python3

"""
PickleViz Ultra96 MQTT + FPGA AI Consumer

Runs in:
    /tmp/comms_venv

Receives:
    Paddle and forearm IMU data through MQTT

Processes:
    200 complete synchronized IMU pairs
    12 channels per sample

Sends:
    [200,12] input to local DPU server

Returns:
    Predicted stroke + confidence

The DPU server runs separately in pynq-venv.
"""

import argparse
import json
import math
import os
import socket
import threading
import time
import uuid

from collections import deque

import _bootstrap

from dotenv import load_dotenv

from utilities.constants import (
    PacketType,
    CA_CERTS_PATH,
    HAPTIC_MIN_INTERVAL_SECONDS,
    HAPTIC_RESULTS_PER_TRIGGER,
    PORT_TLS,
    SENSOR_SOURCES,
    TOPIC_HAPTICS,
    TOPIC_RESULTS,
    TOPIC_SENSOR,
    TRANSPORT_TLS,
)

from utilities.logger_setup import get_logger
from utilities.mqtt_client import MQTTClientWrapper


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

USER_ULTRA96 = os.getenv("USER_ULTRA96")
PW_ULTRA96 = os.getenv("PW_ULTRA96")

parser = argparse.ArgumentParser()
parser.add_argument("-v", "--verbose", action="store_true")
args = parser.parse_args()

logger = get_logger("ultra96", verbose=args.verbose)

# Existing local PYNQ inference server
DPU_SOCKET_PATH = "/tmp/pickleviz_dpu.sock"
DPU_TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 65536

# CNN input
SAMPLES_PER_STROKE = 200
IMU_CHANNELS = 12

# One sample = six paddle + six forearm channels
CLASSES = [
    "forehand",
    "backhand",
    "overhead_stroke",
    "overhead_smash",
    "underhand_short_arch",
    "underhand_long_arch",
]

# Maximum queued windows awaiting DPU inference
MAX_PENDING_WINDOWS = 20

# Optional acquisition gap check.
# Set after confirming actual sensor sampling rate.
MAX_SAMPLE_GAP_MS = None

# Resolve the CA certificate relative to /,
# matching the existing communications installation.
#
# Confirm that /comms/ca.crt exists.
CA_CERTIFICATE = "/comms/ca.crt"


# ============================================================
# MQTT CLIENT
# ============================================================

client = MQTTClientWrapper(
    client_id="ultra96",
    port=PORT_TLS,
    transport=TRANSPORT_TLS,
    ca_certs=CA_CERTIFICATE,
    username=USER_ULTRA96,
    password=PW_ULTRA96,
    lwt_topic="sys/ultra96/status",
    lwt_payload="offline",
    logger=logger,
)


# ============================================================
# RESULT / HAPTIC STATE
# ============================================================

result_seq = 0
result_session_id = uuid.uuid4().hex
result_lock = threading.Lock()

haptic_seq = 0
results_since_haptic = 0
last_haptic_time = float("-inf")


# ============================================================
# SENSOR BUFFER STATE
# ============================================================

sensor_sources = tuple(SENSOR_SOURCES.values())

sensor_buffers = {
    source: deque()
    for source in sensor_sources
}

sensor_sessions = {
    source: None
    for source in sensor_sources
}

sensor_last_seq = {
    source: None
    for source in sensor_sources
}

sensor_last_timestamp = {
    source: None
    for source in sensor_sources
}

sensor_changed = threading.Condition()

pending_windows = deque()


# ============================================================
# DECODE ACTUAL MQTT IMU FORMAT
# ============================================================

def decode_imu(imu):
    """
    Real MQTT IMU format:

    {
        "acceleration": {
            "x": 0.1,
            "y": 0.2,
            "z": 9.8
        },
        "gyroscope": {
            "x": 0.3,
            "y": 0.4,
            "z": 0.5
        }
    }

    Returns:
        [ax, ay, az, gx, gy, gz]
    """

    if not isinstance(imu, dict):
        raise ValueError("Missing IMU data")

    try:
        acceleration = imu["acceleration"]
        gyroscope = imu["gyroscope"]

        values = [
            acceleration["x"],
            acceleration["y"],
            acceleration["z"],
            gyroscope["x"],
            gyroscope["y"],
            gyroscope["z"],
        ]

    except (KeyError, TypeError) as exc:
        raise ValueError(
            "Invalid acceleration/gyroscope format"
        ) from exc

    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        for value in values
    ):
        raise ValueError(
            "Non-numeric IMU measurement"
        )

    values = [float(v) for v in values]

    if not all(math.isfinite(v) for v in values):
        raise ValueError(
            "Non-finite IMU measurement"
        )

    return values


# ============================================================
# VALIDATE COMPLETE SENSOR PAIR
# ============================================================

def decode_sensor_pair(packet):
    paddle_data = packet.get("paddle")
    forearm_data = packet.get("forearm")

    if paddle_data is None and forearm_data is None:
        raise ValueError("Both IMUs unavailable")

    paddle = (
        decode_imu(paddle_data)
        if paddle_data is not None
        else [0.0] * 6
    )

    forearm = (
        decode_imu(forearm_data)
        if forearm_data is not None
        else [0.0] * 6
    )

    return paddle + forearm



# ============================================================
# CONVERT BUFFER INTO CNN WINDOW
# ============================================================

def prepare_imu_window(pairs):

    if len(pairs) != SAMPLES_PER_STROKE:
        raise ValueError(
            f"Expected 200 samples, received {len(pairs)}"
        )

    ordered = sorted(
        pairs,
        key=lambda packet: packet["sensor_seq"]
    )

    session_ids = {
        packet["session_id"]
        for packet in ordered
    }

    if len(session_ids) != 1:
        raise ValueError(
            "Mixed sensor sessions"
        )

    for previous, current in zip(
        ordered,
        ordered[1:]
    ):

        if (
            current["sensor_seq"]
            <= previous["sensor_seq"]
        ):
            raise ValueError(
                "Duplicate or out-of-order sensor sequence"
            )

        if (
            current["timestamp"]
            < previous["timestamp"]
        ):
            raise ValueError(
                "Non-monotonic sensor timestamps"
            )

    samples = [
        decode_sensor_pair(packet)
        for packet in ordered
    ]

    return samples


# ============================================================
# SEND DATA TO DPU SERVER
# ============================================================

def request_dpu_prediction(samples):
    """
    Send [200,12] samples to:
        /tmp/pickleviz_dpu.sock

    Returns:
        stroke, confidence
    """

    if len(samples) != SAMPLES_PER_STROKE:
        raise ValueError(
            "Incorrect CNN input length"
        )

    request = {
        "samples": samples
    }

    payload = (
        json.dumps(request) + "\n"
    ).encode("utf-8")

    with socket.socket(
        socket.AF_UNIX,
        socket.SOCK_STREAM
    ) as connection:

        connection.settimeout(
            DPU_TIMEOUT_SECONDS
        )

        connection.connect(
            DPU_SOCKET_PATH
        )

        connection.sendall(payload)

        response = bytearray()

        while not response.endswith(b"\n"):

            chunk = connection.recv(4096)

            if not chunk:
                raise RuntimeError(
                    "DPU server disconnected"
                )

            response.extend(chunk)

            if len(response) > MAX_RESPONSE_BYTES:
                raise RuntimeError(
                    "DPU response too large"
                )

    result = json.loads(
        response.decode("utf-8")
    )

    if not isinstance(result, dict):
        raise RuntimeError(
            "Invalid DPU response"
        )

    if not result.get("ok"):
        raise RuntimeError(
            result.get(
                "error",
                "DPU inference failed"
            )
        )

    stroke = result["stroke"]
    confidence = float(result["confidence"])

    if stroke not in CLASSES:
        raise ValueError(
            f"Unknown predicted stroke: {stroke}"
        )

    if not math.isfinite(confidence):
        raise ValueError(
            "Invalid confidence"
        )

    if not 0.0 <= confidence <= 1.0:
        raise ValueError(
            "Confidence outside valid range"
        )

    return stroke, confidence


# ============================================================
# PUBLISH AI RESULT
# ============================================================

def publish_ai_result(stroke, confidence, pairs):
    """
    Preserve the original communications result schema.
    """

    global result_seq
    global results_since_haptic
    global haptic_seq
    global last_haptic_time

    source = pairs[-1]["source"]
    sensor_seq = pairs[-1]["sensor_seq"]
    sensor_session_id = pairs[-1]["session_id"]

    with result_lock:

        result_seq += 1

        result = {
            "type": PacketType.AI_RESULTS,
            "source": source,
            "timestamp": (
                time.monotonic_ns() // 1_000_000
            ),
            "session_id": result_session_id,
            "sensor_session_id": sensor_session_id,
            "result_seq": result_seq,
            "sensor_seq": sensor_seq,
            "stroke": stroke,
            "confidence": confidence,

            "sensor_sample_counts": {
                name: sum(
                    packet.get(name) is not None
                    for packet in pairs
                )
                for name in ("forearm", "paddle")
            },

            "complete_pairs": sum(
                packet.get("forearm") is not None
                and packet.get("paddle") is not None
                for packet in pairs
            ),
        }

        if not client.publish(
            TOPIC_RESULTS,
            result,
            qos=1
        ):
            logger.info(
                "Dropped AI result while MQTT unavailable"
            )
            return

        logger.info(
            "Published AI result #%d: "
            "source=%s seq=%d stroke=%s "
            "confidence=%.4f",
            result_seq,
            source,
            sensor_seq,
            stroke,
            confidence
        )

        # Dummy source never triggers haptics.
        if source == "dummy":
            return

        results_since_haptic += 1
        now = time.monotonic()

        if (
            results_since_haptic >= HAPTIC_RESULTS_PER_TRIGGER
            and now - last_haptic_time
            >= HAPTIC_MIN_INTERVAL_SECONDS
        ):

            next_haptic_seq = haptic_seq + 1

            published = client.publish(
                TOPIC_HAPTICS,
                {
                    "type": PacketType.HAPTIC_CMD,
                    "timestamp": (
                        time.monotonic_ns() // 1_000_000
                    ),
                    "session_id": result_session_id,
                    "sensor_session_id": sensor_session_id,
                    "haptic_seq": next_haptic_seq,
                    "result_seq": result_seq,
                    "sensor_seq": sensor_seq,
                    "pattern": "double_pulse",
                },
                qos=1
            )

            if published:
                haptic_seq = next_haptic_seq
                results_since_haptic = 0
                last_haptic_time = now


# ============================================================
# MQTT SENSOR CALLBACK
# ============================================================

def handle_sensor_data(msg):

    try:
        sensor = json.loads(
            msg.payload.decode("utf-8")
        )

    except (ValueError, UnicodeDecodeError):
        logger.warning(
            "Ignoring malformed MQTT sensor packet"
        )
        return

    if (
        not isinstance(sensor, dict)
        or sensor.get("type") != PacketType.SENSOR_DATA
        or sensor.get("source") not in sensor_sources
        or not isinstance(sensor.get("session_id"), str)
        or not sensor["session_id"]
        or type(sensor.get("sensor_seq")) is not int
        or sensor["sensor_seq"] < 1
        or type(sensor.get("timestamp")) is not int
    ):
        logger.warning(
            "Ignoring invalid MQTT sensor packet"
        )
        return

    source = sensor["source"]
    session_id = sensor["session_id"]
    sequence = sensor["sensor_seq"]
    timestamp = sensor["timestamp"]

    # Accept packets with at least one valid IMU.
    # Missing sensor channels are zero-filled.

    try:
        decode_sensor_pair(sensor)

    except ValueError as exc:
        logger.debug(
            "Incomplete %s sensor pair: %s",
            source,
            exc
        )
        return

    with sensor_changed:

        # Independent stream/dummy sessions
        if sensor_sessions[source] != session_id:

            sensor_buffers[source].clear()

            sensor_last_seq[source] = None
            sensor_last_timestamp[source] = None

            sensor_sessions[source] = session_id

            retained = [
                item for item in pending_windows
                if item[0] != source
            ]

            pending_windows.clear()
            pending_windows.extend(retained)

            logger.info(
                "New %s sensor session: %s",
                source,
                session_id
            )

        previous_seq = sensor_last_seq[source]
        previous_timestamp = (
            sensor_last_timestamp[source]
        )

        if previous_seq is not None:

            if sequence <= previous_seq:
                logger.debug(
                    "Discarding duplicate/out-of-order packet"
                )
                return

            if sequence != previous_seq + 1:

                logger.warning(
                    "Sequence gap for %s: %d -> %d",
                    source,
                    previous_seq,
                    sequence
                )

            if timestamp < previous_timestamp:

                logger.warning(
                    "Timestamp moved backwards"
                )

                sensor_buffers[source].clear()

            elif (
                MAX_SAMPLE_GAP_MS is not None
                and timestamp - previous_timestamp
                > MAX_SAMPLE_GAP_MS
            ):

                logger.warning(
                    "Large acquisition gap"
                )

                sensor_buffers[source].clear()

        sensor_last_seq[source] = sequence
        sensor_last_timestamp[source] = timestamp

        buffer = sensor_buffers[source]
        buffer.append(sensor)

        if len(buffer) >= SAMPLES_PER_STROKE:

            pairs = [
                buffer.popleft()
                for _ in range(SAMPLES_PER_STROKE)
            ]

            if len(pending_windows) >= MAX_PENDING_WINDOWS:

                logger.warning(
                    "Inference queue full; "
                    "dropping oldest window"
                )

                pending_windows.popleft()

            pending_windows.append(
                (
                    source,
                    session_id,
                    pairs
                )
            )

            sensor_changed.notify()


# ============================================================
# PROCESS ONE WINDOW
# ============================================================

def process_sensor_window(pairs):

    source = pairs[-1]["source"]

    try:

        samples = prepare_imu_window(
            pairs
        )

        logger.info(
            "Sending %d x %d IMU window to DPU",
            len(samples),
            IMU_CHANNELS
        )

        stroke, confidence = request_dpu_prediction(
            samples
        )

        logger.info(
            "DPU prediction: %s confidence=%.4f",
            stroke,
            confidence
        )

        publish_ai_result(
            stroke,
            confidence,
            pairs
        )

    except (
        ValueError,
        RuntimeError,
        OSError,
        KeyError
    ) as exc:

        logger.warning(
            "Skipping %s AI window: %s",
            source,
            exc
        )


# ============================================================
# MQTT SUBSCRIPTION
# ============================================================

client.subscribe(
    TOPIC_SENSOR,
    callback=handle_sensor_data,
    qos=0
)

client.enable_latency("ultra96")


# ============================================================
# MAIN
# ============================================================

def main():

    if not os.path.exists(DPU_SOCKET_PATH):
        logger.error(
            "DPU socket missing: %s",
            DPU_SOCKET_PATH
        )
        logger.error(
            "Start dpu_server.py in pynq-venv first"
        )
        return

    logger.info(
        "PickleViz MQTT-to-DPU consumer starting"
    )

    logger.info(
        "Expected CNN input: %d x %d",
        SAMPLES_PER_STROKE,
        IMU_CHANNELS
    )

    client.loop_start()

    try:

        while True:

            with sensor_changed:

                while not pending_windows:
                    sensor_changed.wait(timeout=0.5)

                source, session_id, pairs = (
                    pending_windows.popleft()
                )

                if sensor_sessions[source] != session_id:
                    continue

            process_sensor_window(pairs)

    except KeyboardInterrupt:

        logger.info(
            "Interrupted - disconnecting from MQTT"
        )

    finally:

        client.loop_stop()


if __name__ == "__main__":
    main()

