import os
from pathlib import Path

BROKER_HOST = os.getenv("BROKER_HOST", "Venices-MacBook-Air.local")
CA_CERTS_PATH = os.getenv("CA_CERTS_PATH", str(Path(__file__).resolve().parents[1] / "broker/certs/ca.crt"))

PORT_TLS = 8883
PORT_WSS = 9001
SAMPLE_FREQ = 200

TRANSPORT_TLS = "tcp"
TRANSPORT_WSS = "websockets"

TOPIC_SENSOR  = "fb/sensor/raw"
TOPIC_RESULTS = "ultra96/ai/results"
TOPIC_HAPTICS = "ultra96/ai/haptics"
TOPIC_RELAY   = "fb/relay/dummy"

STROKES = ["forehand", "backhand", "overhead stroke", "overhead smash", 
           "underhand short arch", "underhand long arch"]

# BLE connection setup
PKT_HELLO_REQ       = 0x01
PKT_HELLO           = 0x02
PKT_CONFIG          = 0x03
PKT_CONFIG_ACK      = 0x04

# BLE clock synchronisation and stream pause/resume
PKT_SYNC_START      = 0x05
PKT_SYNC_REQ        = 0x06
PKT_SYNC_RESP       = 0x07
PKT_SYNC_END        = 0x08

# Sensor data: FireBeetle binary batch, then laptop paired MQTT sample
PKT_SENSOR_BATCH    = 0x09
PKT_SENSOR_DATA     = 0x0A

# Ultra96 inference output and haptic feedback
PKT_AI_RESULTS      = 0x0B
PKT_HAPTIC_CMD      = 0x0C
PKT_HAPTIC_RESP     = 0x0D

# Keyboard mode: BLE trigger, legacy reply, and paired MQTT batch envelope
PKT_DUMMY           = 0x0E
PKT_DUMMY_REPLY     = 0x0F
PKT_DUMMY_BATCH     = 0x10

# BLE file transfer
PKT_FILE_REQ        = 0x11
PKT_FILE_META       = 0x12
PKT_FILE_CHUNK      = 0x13
PKT_FILE_CHUNK_REQ  = 0x14
PKT_FILE_RESULT     = 0x15

SENSOR_BATCH_SIZE = 5
MAX_SYNC_RTT_MS = 50.0
BLE_WRITE_TIMEOUT_SECONDS = 1.0
HAPTIC_MIN_INTERVAL_SECONDS = 10.0
HAPTIC_RESULTS_PER_TRIGGER = 10

SERVICE_UUID = "25E2CCC3-D857-49A6-AFDC-F6895F1854B0"
NOTIFY_CHAR_UUID = "2F752BBE-B112-4F11-9789-093262B39116"
WRITE_CHAR_UUID = "A9A6FB55-B997-4A3B-A9FA-D97C1E23DB5F"
