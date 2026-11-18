#ifndef CALIBRATION_H
#define CALIBRATION_H

#include "SensorFrame.h"


struct GyroCalibration {
  float biasX;
  float biasY;
  float biasZ;
};

struct AccelCalibration {
  float offsetX_g;
  float offsetY_g;
  float offsetZ_g;
  float scaleX = 1.0f;
  float scaleY = 1.0f;
  float scaleZ = 1.0f;
};


// Function used to calibrate the gyroscope.
//
// readSensor:
//   Function that provides one SensorFrame.
//
// calibrationSamples:
//   Number of samples used to estimate gyro bias.
//
// sampleDelayMs:
//   Delay between calibration samples.
GyroCalibration calibrateGyroscope(
  SensorFrame (*readSensor)(),
  int calibrationSamples,
  unsigned long sampleDelayMs
);

AccelCalibration fixedAccelerometerCalibration();
void applyAccelerometerCalibration(SensorFrame& frame, const AccelCalibration& calibration);

#endif
