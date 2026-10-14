#pragma once
#include "SensorFrame.h"
#include <stddef.h>

// Little-endian ESP32 wire format. Matched by ble_receiver.py; never send
// SensorFrame directly (its layout is compiler-dependent).
#pragma pack(push, 1)
struct BleHeader {
  char magic[2] = {'C', 'G'};
  uint8_t version = 1, node = 1, count = 0, reserved = 0;
  uint32_t boot = 0, session = 0, burst = 0;
};
struct BleSample {
  uint32_t seq, timestampUs, intervalUs;
  float ax, ay, az, gx, gy, gz;
  uint8_t status, event;  // event: bit 0=start, bit 1=normal end
};
#pragma pack(pop)
static_assert(sizeof(BleHeader) == 18, "BLE header layout");
static_assert(sizeof(BleSample) == 38, "BLE sample layout");
constexpr size_t BLE_BATCH_SIZE = 4;
constexpr size_t BLE_PACKET_BYTES = sizeof(BleHeader) + BLE_BATCH_SIZE * sizeof(BleSample);
constexpr uint16_t BLE_MIN_MTU = 3 + sizeof(BleHeader) + sizeof(BleSample);

inline BleSample makeBleSample(const SensorFrame& f, uint8_t event) {
  return {f.seq, static_cast<uint32_t>(f.timestamp_us), static_cast<uint32_t>(f.interval_us),
          f.ax_filtered_g, f.ay_filtered_g, f.az_filtered_g,
          f.gx_filtered_dps, f.gy_filtered_dps, f.gz_filtered_dps, f.status_flags, event};
}
