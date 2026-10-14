#ifndef AXIS_MAPPING_H
#define AXIS_MAPPING_H

#include "SensorFrame.h"

enum SensorAxis : uint8_t {
  SENSOR_AXIS_X = 0,
  SENSOR_AXIS_Y = 1,
  SENSOR_AXIS_Z = 2
};

struct AxisMapping {
  SensorAxis canonicalXSource;
  int8_t canonicalXSign;
  SensorAxis canonicalYSource;
  int8_t canonicalYSign;
  SensorAxis canonicalZSource;
  int8_t canonicalZSign;
};

// Current provisional mapping: IMU axes equal canonical axes.
const AxisMapping AXIS_MAPPING_IDENTITY = {
  SENSOR_AXIS_X, 1,
  SENSOR_AXIS_Y, 1,
  SENSOR_AXIS_Z, 1
};

// Example: canonical X=-sensor Y, canonical Y=sensor X, canonical Z=sensor Z.
const AxisMapping AXIS_MAPPING_SWAP_XY_FLIP_X = {
  SENSOR_AXIS_Y, -1,
  SENSOR_AXIS_X, 1,
  SENSOR_AXIS_Z, 1
};

// Example: canonical X=sensor X, canonical Y=-sensor Z, canonical Z=sensor Y.
const AxisMapping AXIS_MAPPING_YZ_ROTATION = {
  SENSOR_AXIS_X, 1,
  SENSOR_AXIS_Z, -1,
  SENSOR_AXIS_Y, 1
};

inline int16_t mappedRawValue(const int16_t values[3], SensorAxis source,
                              int8_t sign) {
  return values[source] * sign;
}

inline float mappedFloatValue(const float values[3], SensorAxis source,
                              int8_t sign) {
  return values[source] * sign;
}

inline void applyAxisMapping(SensorFrame& frame, const AxisMapping& mapping) {
  const int16_t rawAccel[3] = {frame.ax, frame.ay, frame.az};
  const int16_t rawGyro[3] = {frame.gx, frame.gy, frame.gz};
  const float accel[3] = {frame.ax_g, frame.ay_g, frame.az_g};
  const float gyro[3] = {frame.gx_dps, frame.gy_dps, frame.gz_dps};

  frame.ax = mappedRawValue(rawAccel, mapping.canonicalXSource,
                            mapping.canonicalXSign);
  frame.ay = mappedRawValue(rawAccel, mapping.canonicalYSource,
                            mapping.canonicalYSign);
  frame.az = mappedRawValue(rawAccel, mapping.canonicalZSource,
                            mapping.canonicalZSign);
  frame.gx = mappedRawValue(rawGyro, mapping.canonicalXSource,
                            mapping.canonicalXSign);
  frame.gy = mappedRawValue(rawGyro, mapping.canonicalYSource,
                            mapping.canonicalYSign);
  frame.gz = mappedRawValue(rawGyro, mapping.canonicalZSource,
                            mapping.canonicalZSign);

  frame.ax_g = mappedFloatValue(accel, mapping.canonicalXSource,
                                mapping.canonicalXSign);
  frame.ay_g = mappedFloatValue(accel, mapping.canonicalYSource,
                                mapping.canonicalYSign);
  frame.az_g = mappedFloatValue(accel, mapping.canonicalZSource,
                                mapping.canonicalZSign);
  frame.gx_dps = mappedFloatValue(gyro, mapping.canonicalXSource,
                                  mapping.canonicalXSign);
  frame.gy_dps = mappedFloatValue(gyro, mapping.canonicalYSource,
                                  mapping.canonicalYSign);
  frame.gz_dps = mappedFloatValue(gyro, mapping.canonicalZSource,
                                  mapping.canonicalZSign);
}

#endif