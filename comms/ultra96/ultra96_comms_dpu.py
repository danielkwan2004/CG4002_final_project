#!/usr/bin/env python3

"""
PickleViz Ultra96 MQTT + FPGA AI Consumer

Receives:
    Paddle and forearm IMU data through MQTT

Live inference:
    1. Continuously maintain recent IMU history.
    2. Detect significant paddle motion.
    3. Capture one aligned 400-sample window.
    4. Send [400,12] to the local DPU server.
    5. Reject low-confidence predictions.
    6. Publish accepted stroke predictions.

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
    PORT_TLS,
    SENSOR_SOURCES,
    TOPIC_HANDEDNESS,
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
parser.add_argument(
    "-v",
    "--verbose",
    action="store_true"
)

args = parser.parse_args()

logger = get_logger(
    "ultra96",
    verbose=args.verbose
)


# ============================================================
# DPU SERVER
# ============================================================

DPU_SOCKET_PATH = "/tmp/pickleviz_dpu.sock"

DPU_TIMEOUT_SECONDS = 5.0

MAX_RESPONSE_BYTES = 65536


# ============================================================
# CNN INPUT
# ============================================================

SAMPLES_PER_STROKE = 400

IMU_CHANNELS = 12


# ============================================================
# CONFIDENCE FILTER
# ============================================================

MIN_CONFIDENCE = 0.70


# ============================================================
# MOTION-TRIGGERED WINDOWING
# ============================================================

# Number of recent samples retained before motion detection.
PRE_TRIGGER_SAMPLES = 100

POST_TRIGGER_SAMPLES = (
    SAMPLES_PER_STROKE
    - PRE_TRIGGER_SAMPLES
)

# Initial motion threshold.
#
# Fresh stroke recordings showed volley gyro peaks around
# roughly 200-326 while full strokes were often much higher.
#
# 100 is therefore a conservative starting trigger.
#
# Tune this later using actual idle measurements.
GYRO_TRIGGER_THRESHOLD = 100.0

# Require several consecutive samples above the threshold.
TRIGGER_CONFIRM_SAMPLES = 3

# Prevent one physical stroke from immediately triggering
# another classification.
STROKE_COOLDOWN_SECONDS = 1.0


# ============================================================
# CLASSES
# ============================================================

CLASSES = [
    "forehand",
    "backhand",
    "overhead",
    "underhand",
    "forehand_volley",
    "backhand_volley",
]


# ============================================================
# QUEUE / SENSOR TIMING
# ============================================================

MAX_PENDING_WINDOWS = 20

# Same basic timing protection used during training capture.
MAX_SAMPLE_GAP_MS = 20


# ============================================================
# TLS
# ============================================================

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


# ============================================================
# SENSOR BUFFER STATE
# ============================================================

sensor_sources = tuple(
    SENSOR_SOURCES.values()
)


# Rolling pre-trigger history.
sensor_buffers = {
    source: deque()
    for source in sensor_sources
}


# Number of consecutive samples above motion threshold.
motion_counts = {
    source: 0
    for source in sensor_sources
}


# Active triggered capture.
#
# None:
#     no stroke currently being captured
#
# dict:
#     {"pairs": [...]}
capture_states = {
    source: None
    for source in sensor_sources
}


# Last completed stroke time for cooldown.
last_stroke_times = {
    source: float("-inf")
    for source in sensor_sources
}


# MQTT sensor session state.
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


# Completed stroke windows waiting for inference.
pending_windows = deque()


# ============================================================
# IMU DECODING
# ============================================================

def decode_imu(imu):
    """
    Decode one IMU.

    Expected format:

    {
        "acceleration": {
            "x": ...,
            "y": ...,
            "z": ...
        },
        "gyroscope": {
            "x": ...,
            "y": ...,
            "z": ...
        }
    }

    Returns:

        [ax, ay, az, gx, gy, gz]
    """

    if not isinstance(imu, dict):
        raise ValueError(
            "Missing IMU data"
        )

    try:

        acceleration = imu[
            "acceleration"
        ]

        gyroscope = imu[
            "gyroscope"
        ]

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
        or not isinstance(
            value,
            (int, float)
        )
        for value in values
    ):

        raise ValueError(
            "Non-numeric IMU measurement"
        )


    values = [
        float(value)
        for value in values
    ]


    if not all(
        math.isfinite(value)
        for value in values
    ):

        raise ValueError(
            "Non-finite IMU measurement"
        )


    return values


# ============================================================
# COMPLETE SENSOR PAIR
# ============================================================

def decode_sensor_pair(packet):
    """
    Return exactly 12 channels:

        paddle:
            ax ay az gx gy gz

        forearm:
            ax ay az gx gy gz

    Both IMUs are required because the CNN was trained using
    complete paddle + forearm samples.
    """

    if packet.get("paddle") is None:

        raise ValueError(
            "Missing paddle IMU"
        )


    if packet.get("forearm") is None:

        raise ValueError(
            "Missing forearm IMU"
        )


    paddle = decode_imu(
        packet["paddle"]
    )

    forearm = decode_imu(
        packet["forearm"]
    )


    return paddle + forearm


# ============================================================
# MOTION MAGNITUDE
# ============================================================

def paddle_gyro_magnitude(packet):
    """
    Calculate paddle gyroscope magnitude.

    sqrt(gx^2 + gy^2 + gz^2)
    """

    paddle = decode_imu(
        packet["paddle"]
    )

    gx = paddle[3]
    gy = paddle[4]
    gz = paddle[5]


    return math.sqrt(
        gx * gx
        + gy * gy
        + gz * gz
    )


# ============================================================
# PREPARE CNN WINDOW
# ============================================================

def prepare_imu_window(pairs):
    """
    Convert 400 synchronized MQTT packets into:

        [400,12]

    The channel order is identical to training.
    """

    if len(pairs) != SAMPLES_PER_STROKE:

        raise ValueError(
            f"Expected "
            f"{SAMPLES_PER_STROKE} samples, "
            f"received {len(pairs)}"
        )


    ordered = sorted(
        pairs,
        key=lambda packet:
            packet["sensor_seq"]
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
                "Duplicate or out-of-order "
                "sensor sequence"
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
# DPU REQUEST
# ============================================================

def request_dpu_prediction(samples):
    """
    Send [400,12] samples to the local DPU server.

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
        json.dumps(request)
        + "\n"
    ).encode(
        "utf-8"
    )


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


        connection.sendall(
            payload
        )


        response = bytearray()


        while not response.endswith(
            b"\n"
        ):

            chunk = connection.recv(
                4096
            )


            if not chunk:

                raise RuntimeError(
                    "DPU server disconnected"
                )


            response.extend(
                chunk
            )


            if (
                len(response)
                > MAX_RESPONSE_BYTES
            ):

                raise RuntimeError(
                    "DPU response too large"
                )


    result = json.loads(
        response.decode(
            "utf-8"
        )
    )


    if not isinstance(
        result,
        dict
    ):

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


    stroke = result[
        "stroke"
    ]

    confidence = float(
        result["confidence"]
    )


    if stroke not in CLASSES:

        raise ValueError(
            f"Unknown predicted stroke: "
            f"{stroke}"
        )


    if not math.isfinite(
        confidence
    ):

        raise ValueError(
            "Invalid confidence"
        )


    if not (
        0.0
        <= confidence
        <= 1.0
    ):

        raise ValueError(
            "Confidence outside valid range"
        )


    return stroke, confidence


# ============================================================
# PUBLISH AI RESULT
# ============================================================

def publish_ai_result(
    stroke,
    confidence,
    pairs
):

    global result_seq
    global haptic_seq


    source = pairs[-1][
        "source"
    ]

    sensor_seq = pairs[-1][
        "sensor_seq"
    ]

    sensor_session_id = pairs[-1][
        "session_id"
    ]


    with result_lock:

        result_seq += 1


        result = {
            "type":
                PacketType.AI_RESULTS,

            "source":
                source,

            "timestamp":
                time.monotonic_ns()
                // 1_000_000,

            "session_id":
                result_session_id,

            "sensor_session_id":
                sensor_session_id,

            "result_seq":
                result_seq,

            "sensor_seq":
                sensor_seq,

            "stroke":
                stroke,

            "confidence":
                confidence,

            "sensor_sample_counts": {
                name: sum(
                    packet.get(name)
                    is not None
                    for packet in pairs
                )
                for name in (
                    "forearm",
                    "paddle"
                )
            },

            "complete_pairs": sum(
                packet.get("forearm")
                is not None
                and packet.get("paddle")
                is not None
                for packet in pairs
            ),
        }


        if not client.publish(
            TOPIC_RESULTS,
            result,
            qos=1
        ):

            logger.info(
                "Dropped AI result while "
                "MQTT unavailable"
            )

            return


        logger.info(
            "Published AI result #%d: "
            "source=%s seq=%d "
            "stroke=%s confidence=%.4f",
            result_seq,
            source,
            sensor_seq,
            stroke,
            confidence
        )


        # Publish one haptic command for every successfully published AI result.
        next_haptic_seq = haptic_seq + 1
        haptic = {
            "type": PacketType.HAPTIC_CMD,
            "timestamp": time.monotonic_ns() // 1_000_000,
            "session_id": result_session_id,
            "sensor_session_id": sensor_session_id,
            "haptic_seq": next_haptic_seq,
            "result_seq": result_seq,
            "sensor_seq": sensor_seq,
            "pattern": "double",
        }

        if not client.publish(TOPIC_HAPTICS, haptic, qos=1):
            logger.info("Dropped haptic command while MQTT unavailable")
            return

        haptic_seq = next_haptic_seq
        logger.info(
            "Published haptic #%d: result_seq=%d sensor_seq=%d",
            haptic_seq,
            result_seq,
            sensor_seq,
        )


# ============================================================
# HANDEDNESS CALLBACK
# ============================================================

def handle_handedness(msg):
    """
    Handedness is product/session metadata.

    It is NOT an input to the current StrokeCNN.
    """

    try:

        handedness = json.loads(
            msg.payload.decode(
                "utf-8"
            )
        )

    except (
        ValueError,
        UnicodeDecodeError
    ):

        logger.warning(
            "Ignoring malformed MQTT "
            "handedness packet"
        )

        return


    if (
        not isinstance(
            handedness,
            dict
        )
        or handedness.get(
            "handedness"
        )
        not in (
            "left",
            "right"
        )
    ):

        logger.warning(
            "Ignoring invalid MQTT "
            "handedness packet"
        )

        return


    logger.info(
        "Received handedness: %s",
        handedness["handedness"]
    )


# ============================================================
# SENSOR CALLBACK
# ============================================================

def handle_sensor_data(msg):

    try:

        sensor = json.loads(
            msg.payload.decode(
                "utf-8"
            )
        )

    except (
        ValueError,
        UnicodeDecodeError
    ):

        logger.warning(
            "Ignoring malformed MQTT "
            "sensor packet"
        )

        return


    # --------------------------------------------------------
    # Validate packet metadata
    # --------------------------------------------------------

    if (
        not isinstance(
            sensor,
            dict
        )

        or sensor.get("type")
        != PacketType.SENSOR_DATA

        or sensor.get("source")
        not in sensor_sources

        or not isinstance(
            sensor.get("session_id"),
            str
        )

        or not sensor[
            "session_id"
        ]

        or type(
            sensor.get("sensor_seq")
        ) is not int

        or sensor[
            "sensor_seq"
        ] < 1

        or type(
            sensor.get("timestamp")
        ) is not int
    ):

        logger.warning(
            "Ignoring invalid MQTT "
            "sensor packet"
        )

        return


    source = sensor[
        "source"
    ]

    session_id = sensor[
        "session_id"
    ]

    sequence = sensor[
        "sensor_seq"
    ]

    timestamp = sensor[
        "timestamp"
    ]


    # --------------------------------------------------------
    # Require BOTH IMUs
    # --------------------------------------------------------

    try:

        decode_sensor_pair(
            sensor
        )

    except ValueError as exc:

        logger.debug(
            "Incomplete %s sensor pair: %s",
            source,
            exc
        )

        return


    # --------------------------------------------------------
    # Protect shared state
    # --------------------------------------------------------

    with sensor_changed:

        # ====================================================
        # NEW SENSOR SESSION
        # ====================================================

        if (
            sensor_sessions[source]
            != session_id
        ):

            sensor_buffers[
                source
            ].clear()


            sensor_last_seq[
                source
            ] = None


            sensor_last_timestamp[
                source
            ] = None


            motion_counts[
                source
            ] = 0


            capture_states[
                source
            ] = None


            last_stroke_times[
                source
            ] = float(
                "-inf"
            )


            sensor_sessions[
                source
            ] = session_id


            # Remove pending windows from
            # the previous session.
            retained = [
                item
                for item
                in pending_windows
                if item[0] != source
            ]


            pending_windows.clear()

            pending_windows.extend(
                retained
            )


            logger.info(
                "New %s sensor session: %s",
                source,
                session_id
            )


        previous_seq = (
            sensor_last_seq[
                source
            ]
        )

        previous_timestamp = (
            sensor_last_timestamp[
                source
            ]
        )


        # ====================================================
        # SEQUENCE / TIMESTAMP CHECKS
        # ====================================================

        if previous_seq is not None:

            if (
                sequence
                <= previous_seq
            ):

                logger.debug(
                    "Discarding duplicate/"
                    "out-of-order packet"
                )

                return


            if (
                sequence
                != previous_seq + 1
            ):

                logger.warning(
                    "Sequence gap for %s: "
                    "%d -> %d",
                    source,
                    previous_seq,
                    sequence
                )


                sensor_buffers[
                    source
                ].clear()


                capture_states[
                    source
                ] = None


                motion_counts[
                    source
                ] = 0


            if (
                timestamp
                < previous_timestamp
            ):

                logger.warning(
                    "Timestamp moved backwards"
                )


                sensor_buffers[
                    source
                ].clear()


                capture_states[
                    source
                ] = None


                motion_counts[
                    source
                ] = 0


            elif (
                MAX_SAMPLE_GAP_MS
                is not None

                and (
                    timestamp
                    - previous_timestamp
                    > MAX_SAMPLE_GAP_MS
                )
            ):

                logger.warning(
                    "Large acquisition gap"
                )


                sensor_buffers[
                    source
                ].clear()


                capture_states[
                    source
                ] = None


                motion_counts[
                    source
                ] = 0


        sensor_last_seq[
            source
        ] = sequence


        sensor_last_timestamp[
            source
        ] = timestamp


        # ====================================================
        # ACTIVE STROKE CAPTURE
        # ====================================================

        capture = capture_states[
            source
        ]


        if capture is not None:

            capture[
                "pairs"
            ].append(
                sensor
            )


            if (
                len(
                    capture[
                        "pairs"
                    ]
                )
                >= SAMPLES_PER_STROKE
            ):

                pairs = (
                    capture[
                        "pairs"
                    ][
                        :SAMPLES_PER_STROKE
                    ]
                )


                capture_states[
                    source
                ] = None


                motion_counts[
                    source
                ] = 0


                last_stroke_times[
                    source
                ] = time.monotonic()


                sensor_buffers[
                    source
                ].clear()


                # Queue overflow protection.
                if (
                    len(
                        pending_windows
                    )
                    >= MAX_PENDING_WINDOWS
                ):

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


                logger.info(
                    "Captured motion-triggered "
                    "%d-sample stroke window",
                    SAMPLES_PER_STROKE
                )


                sensor_changed.notify()


            return


        # ====================================================
        # PRE-TRIGGER ROLLING HISTORY
        # ====================================================

        buffer = sensor_buffers[
            source
        ]


        buffer.append(
            sensor
        )


        while (
            len(buffer)
            > PRE_TRIGGER_SAMPLES
        ):

            buffer.popleft()


        # ====================================================
        # COOLDOWN
        # ====================================================

        if (
            time.monotonic()
            - last_stroke_times[
                source
            ]
            < STROKE_COOLDOWN_SECONDS
        ):

            motion_counts[
                source
            ] = 0

            return


        # ====================================================
        # MOTION DETECTION
        # ====================================================

        try:

            gyro_mag = (
                paddle_gyro_magnitude(
                    sensor
                )
            )

        except (
            ValueError,
            KeyError
        ):

            motion_counts[
                source
            ] = 0

            return


        if (
            gyro_mag
            >= GYRO_TRIGGER_THRESHOLD
        ):

            motion_counts[
                source
            ] += 1

        else:

            motion_counts[
                source
            ] = 0


        # ====================================================
        # START A NEW STROKE CAPTURE
        # ====================================================

        if (
            motion_counts[
                source
            ]
            >= TRIGGER_CONFIRM_SAMPLES
        ):

            pre_samples = list(
                buffer
            )[
                -PRE_TRIGGER_SAMPLES:
            ]


            capture_states[
                source
            ] = {
                "pairs":
                    pre_samples
            }


            logger.info(
                "Stroke motion detected: "
                "gyro=%.2f "
                "pre_samples=%d",
                gyro_mag,
                len(
                    pre_samples
                )
            )


            motion_counts[
                source
            ] = 0


# ============================================================
# PROCESS ONE COMPLETED STROKE WINDOW
# ============================================================

def process_sensor_window(
    pairs
):

    source = pairs[-1][
        "source"
    ]


    try:

        samples = prepare_imu_window(
            pairs
        )


        logger.info(
            "Sending %d x %d "
            "IMU window to DPU",
            len(samples),
            IMU_CHANNELS
        )


        stroke, confidence = (
            request_dpu_prediction(
                samples
            )
        )


        logger.info(
            "DPU prediction: "
            "%s confidence=%.4f",
            stroke,
            confidence
        )


        # ----------------------------------------------------
        # CONFIDENCE REJECTION
        # ----------------------------------------------------

        if (
            confidence
            < MIN_CONFIDENCE
        ):

            logger.info(
                "Rejected low-confidence "
                "prediction: "
                "%s confidence=%.4f "
                "threshold=%.2f",
                stroke,
                confidence,
                MIN_CONFIDENCE
            )

            return


        # ----------------------------------------------------
        # ACCEPTED RESULT
        # ----------------------------------------------------

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
# MQTT SUBSCRIPTIONS
# ============================================================

client.subscribe(
    TOPIC_SENSOR,
    callback=handle_sensor_data,
    qos=0
)


client.subscribe(
    TOPIC_HANDEDNESS,
    callback=handle_handedness,
    qos=1
)


client.enable_latency(
    "ultra96"
)


# ============================================================
# MAIN
# ============================================================

def main():

    if not os.path.exists(
        DPU_SOCKET_PATH
    ):

        logger.error(
            "DPU socket missing: %s",
            DPU_SOCKET_PATH
        )

        logger.error(
            "Start dpu_server.py in "
            "pynq-venv first"
        )

        return


    logger.info(
        "PickleViz MQTT-to-DPU "
        "consumer starting"
    )


    logger.info(
        "Expected CNN input: "
        "%d x %d",
        SAMPLES_PER_STROKE,
        IMU_CHANNELS
    )


    logger.info(
        "Motion trigger: "
        "gyro >= %.2f for %d samples",
        GYRO_TRIGGER_THRESHOLD,
        TRIGGER_CONFIRM_SAMPLES
    )


    logger.info(
        "Window alignment: "
        "%d pre-trigger + %d post-trigger",
        PRE_TRIGGER_SAMPLES,
        POST_TRIGGER_SAMPLES
    )


    logger.info(
        "Confidence threshold: %.2f",
        MIN_CONFIDENCE
    )


    client.loop_start()


    try:

        while True:

            with sensor_changed:

                while not pending_windows:

                    sensor_changed.wait(
                        timeout=0.5
                    )


                source, session_id, pairs = (
                    pending_windows.popleft()
                )


                if (
                    sensor_sessions[
                        source
                    ]
                    != session_id
                ):

                    continue


            # Run DPU outside the condition lock.
            process_sensor_window(
                pairs
            )


    except KeyboardInterrupt:

        logger.info(
            "Interrupted - "
            "disconnecting from MQTT"
        )


    finally:

        client.loop_stop()


if __name__ == "__main__":
    main()
