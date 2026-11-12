#pragma once
#include <stdint.h>
#include <stddef.h>
#include "NodeConfig.h"

// These identifiers and packet fields match imu_wifi_battery_test/BLE.ino.
#define SERVICE_UUID     "25E2CCC3-D857-49A6-AFDC-F6895F1854B0"
#define NOTIFY_CHAR_UUID "2F752BBE-B112-4F11-9789-093262B39116"
#define WRITE_CHAR_UUID  "A9A6FB55-B997-4A3B-A9FA-D97C1E23DB5F"
#define NODE_ID (SOM_NODE_ROLE == SOM_PADDLE ? "paddle" : "forearm")

enum PacketType : uint8_t {
  PKT_HELLO_REQ=0x01, PKT_HELLO=0x02, PKT_CONFIG=0x03, PKT_CONFIG_ACK=0x04,
  PKT_SYNC_START=0x05, PKT_SYNC_REQ=0x06, PKT_SYNC_RESP=0x07, PKT_SYNC_END=0x08,
  PKT_SENSOR_BATCH=0x09, PKT_HAPTIC_CMD=0x0C, PKT_HAPTIC_RESP=0x0D, PKT_DUMMY=0x0E
};
enum ConnState { DISCONNECTED, CONNECTED, HELLO_SENT, CONFIGURED, SYNCHRONISED };
constexpr uint8_t SENSOR_BATCH_SIZE = 5;
constexpr uint32_t CAPTURE_DURATION_MS = 1000;

#pragma pack(push, 1)
struct SensorSample {
  uint32_t sequence, timestamp;  // BLE sequence and millis(), NOT micros().
  float accel[3];               // m/s^2, including gravity
  float gyro[3];                // degrees/s
};
struct SensorBatchPayload {
  uint8_t type=PKT_SENSOR_BATCH, count=0, source=0;
  SensorSample samples[SENSOR_BATCH_SIZE];
};
#pragma pack(pop)
static_assert(sizeof(SensorSample)==32, "Client expects little-endian <II6f");
static_assert(sizeof(SensorBatchPayload)==163, "Client expects 3+5*32 bytes");

// BLE callbacks only publish link events and incoming commands. The Arduino
// loop alone owns protocol state, batches and notifications.
struct BleLinkState {
  uint32_t generation=0;
  uint16_t handle=0xffff, mtu=23;
  bool subscribed=false;
};
struct BleCommand {
  char json[768]; // Full haptic JSON includes session IDs and 64-bit host timestamps.
  uint32_t receivedMs, generation;
};
struct Notification {
  uint8_t bytes[sizeof(SensorBatchPayload)];
  size_t length;
};
void printBleHealth();
