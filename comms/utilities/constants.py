import os
from pathlib import Path
import struct
from enum import IntEnum, unique

BROKER_HOST = os.getenv("BROKER_HOST", "Venices-MacBook-Air.local")
CA_CERTS_PATH = os.getenv("CA_CERTS_PATH", str(Path(__file__).resolve().parents[1] / "broker/certs/ca.crt"))

PORT_TLS = 8883
PORT_WSS = 9001

TRANSPORT_TLS = "tcp"
TRANSPORT_WSS = "websockets"

# Shared MQTT routes; the Unity client keeps matching topic strings in C#.
TOPIC_SENSOR  = "fb/sensor/raw"
TOPIC_RESULTS = "ultra96/ai/results"
TOPIC_HAPTICS = "ultra96/ai/haptics"
TOPIC_LATENCY_REQUEST = "latency/{device}/req"
TOPIC_LATENCY_RESPONSE = "latency/{device}/resp"

STROKES = ["forehand", "backhand", "overhead stroke", "overhead smash", 
           "underhand short arch", "underhand long arch"]


# Standard little-endian sizes, without native alignment: 2 uint32 + 6 float32
# values = 32 bytes. The firmware packed struct must keep this exact field order.
SENSOR_SAMPLE_STRUCT = struct.Struct("<II6f")
SENSOR_SOURCES = {0: "stream", 1: "dummy"}

# IntEnum values remain numeric on the wire. packet_type_name() is only for
# readable logs, so changing a display label does not change a packet ID.
@unique
class PacketType(IntEnum):
    """Packet types: TYPE = 0xNN"""
    # BLE connection setup
    HELLO_REQ       = 0x01
    HELLO           = 0x02
    CONFIG          = 0x03
    CONFIG_ACK      = 0x04

    # BLE clock synchronisation and stream pause/resume
    SYNC_START      = 0x05
    SYNC_REQ        = 0x06
    SYNC_RESP       = 0x07
    SYNC_END        = 0x08

    # Sensor data: FireBeetle binary batch, then laptop paired MQTT sample
    SENSOR_BATCH    = 0x09
    SENSOR_DATA     = 0x0A

    # Ultra96 inference output and haptic feedback
    AI_RESULTS      = 0x0B
    HAPTIC_CMD      = 0x0C
    HAPTIC_RESP     = 0x0D

    # User-triggered capture; replies use the ordinary sensor batch.
    DUMMY           = 0x0E

    # BLE file transfer
    FILE_REQ        = 0x11
    FILE_META       = 0x12
    FILE_CHUNK      = 0x13
    FILE_CHUNK_REQ  = 0x14
    FILE_RESULT     = 0x15

# Compatibility imports for the untouched legacy sim_ultra96.py script.
PKT_AI_RESULTS = PacketType.AI_RESULTS
PKT_HAPTIC_CMD = PacketType.HAPTIC_CMD

SENSOR_BATCH_SIZE = 5
MAX_SYNC_RTT_MS = 50.0
BLE_WRITE_TIMEOUT_SECONDS = 1.0
HAPTIC_MIN_INTERVAL_SECONDS = 10.0
HAPTIC_RESULTS_PER_TRIGGER = 10

SERVICE_UUID = "25E2CCC3-D857-49A6-AFDC-F6895F1854B0"
NOTIFY_CHAR_UUID = "2F752BBE-B112-4F11-9789-093262B39116"
WRITE_CHAR_UUID = "A9A6FB55-B997-4A3B-A9FA-D97C1E23DB5F"


def packet_type_name(packet_type):
    """Readable log label for an enum member or raw numeric wire ID."""
    if packet_type is None:
        return "MISSING_TYPE"
    if type(packet_type) not in (int, PacketType):
        return f"INVALID_TYPE({packet_type!r})"
    try:
        name = PacketType(packet_type).name
    except ValueError:
        name = "UNKNOWN"
    return f"{name} (0x{int(packet_type):02X})"
