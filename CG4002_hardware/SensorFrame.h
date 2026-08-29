#ifndef SENSOR_FRAME_H
#define SENSOR_FRAME_H

#include <Arduino.h>

struct SensorFrame {
  unsigned long timestamp_us;

  int16_t ax;
  int16_t ay;
  int16_t az;

  int16_t gx;
  int16_t gy;
  int16_t gz;
};

#endif