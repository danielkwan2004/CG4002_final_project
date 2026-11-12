#include <Arduino.h>
#include "Calibration.h"
#include "AccelCalibrationConfig.h"


GyroCalibration calibrateGyroscope(
  SensorFrame (*readSensor)(),
  int calibrationSamples,
  unsigned long sampleDelayMs
) {

  long sumX = 0;
  long sumY = 0;
  long sumZ = 0;


  for (int i = 0; i < calibrationSamples; i++) {

    SensorFrame frame = readSensor();

    sumX += frame.gx;
    sumY += frame.gy;
    sumZ += frame.gz;

    delay(sampleDelayMs);
  }


  GyroCalibration calibration;

  calibration.biasX =
      (float)sumX / calibrationSamples;

  calibration.biasY =
      (float)sumY / calibrationSamples;

  calibration.biasZ =
      (float)sumZ / calibrationSamples;


  return calibration;
}

AccelCalibration fixedAccelerometerCalibration() {
  return {AccelCalibrationConfig::OFFSET_G[0], AccelCalibrationConfig::OFFSET_G[1],
          AccelCalibrationConfig::OFFSET_G[2], AccelCalibrationConfig::SCALE[0],
          AccelCalibrationConfig::SCALE[1], AccelCalibrationConfig::SCALE[2]};
}

void applyAccelerometerCalibration(SensorFrame& frame, const AccelCalibration& calibration) {
  frame.ax_g = (frame.ax_g - calibration.offsetX_g) / calibration.scaleX;
  frame.ay_g = (frame.ay_g - calibration.offsetY_g) / calibration.scaleY;
  frame.az_g = (frame.az_g - calibration.offsetZ_g) / calibration.scaleZ;
}
