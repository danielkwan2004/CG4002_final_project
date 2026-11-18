#ifndef SENSOR_FRAME_H
#define SENSOR_FRAME_H

#include <stdint.h>

enum SensorStatusFlags : uint8_t {
  SENSOR_STATUS_NONE = 0x00,
  SENSOR_STATUS_SATURATED = 0x01,
  SENSOR_STATUS_PHYSICAL_UNITS_VALID = 0x02,
  SENSOR_STATUS_CALIBRATED = 0x04,
  SENSOR_STATUS_MOVE_ACTIVE = 0x08,
  // Experimental continuous capture; MOVE_ACTIVE still means the legacy gate.
  SENSOR_STATUS_CONTINUOUS_CAPTURE = 0x10
};

struct SensorFrame {
  unsigned long timestamp_us;
  unsigned long interval_us;  // Since previous completed read; first sample=0
  uint8_t node_id;

  uint32_t seq;

  int16_t ax;
  int16_t ay;
  int16_t az;

  int16_t gx;
  int16_t gy;
  int16_t gz;

  float ax_g;
  float ay_g;
  float az_g;

  float gx_dps;
  float gy_dps;
  float gz_dps;

  float ax_filtered_g;
  float ay_filtered_g;
  float az_filtered_g;

  float gx_filtered_dps;
  float gy_filtered_dps;
  float gz_filtered_dps;

  uint8_t status_flags;
};

#endif
