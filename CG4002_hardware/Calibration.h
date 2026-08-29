#ifndef CALIBRATION_H
#define CALIBRATION_H

#include "SensorFrame.h"


struct GyroCalibration {
  float biasX;
  float biasY;
  float biasZ;
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

#endif