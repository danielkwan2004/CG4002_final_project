#pragma once
#include <Arduino.h>
#include "BleQueue.h"

// Dedicated UUIDs avoid confusing this movement-gated protocol with the
// reference sketch's handshake, units and packet layout.
constexpr const char* BLE_SERVICE_UUID = "b26b1000-0ec1-4b8c-9f78-f25e5c9d4002";
constexpr const char* BLE_NOTIFY_UUID  = "b26b1001-0ec1-4b8c-9f78-f25e5c9d4002";
constexpr const char* BLE_STATUS_UUID  = "b26b1002-0ec1-4b8c-9f78-f25e5c9d4002";

struct BleLink { uint16_t handle = 0xffff, mtu = 23; bool subscribed = false; uint32_t session = 0; };
class BleTelemetry {
public:
  bool begin(const char* name, uint8_t node, uint32_t boot);
  void enqueue(const SensorFrame& frame, uint32_t burst, uint8_t event);
  void service();
  void setStatus(const char* json);
  BleLink link() const;
  const BleQueue& counters() const { return queue; }
  uint32_t offlineSamples() const { return offline; }
private:
  BleLink syncLink();
  BleQueue queue;
  uint8_t nodeId = 1;
  uint32_t bootId = 0, session = 0, offline = 0, lastAdvertiseMs = 0;
};
