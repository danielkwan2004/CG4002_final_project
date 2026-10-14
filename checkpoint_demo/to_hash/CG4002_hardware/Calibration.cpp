#include <Arduino.h>
#include "Calibration.h"


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

AccelCalibration calibrateAccelerometer(
  SensorFrame (*readSensor)(),
  int calibrationSamples,
  unsigned long sampleDelayMs
) {

  float sumX = 0.0;
  float sumY = 0.0;
  float sumZ = 0.0;

  Serial.println("Keep sensor flat with +Z upward...");
  Serial.println("Calibrating accelerometer...");

  for (int i = 0; i < calibrationSamples; i++) {
    SensorFrame frame = readSensor();
    sumX += frame.ax_g;
    sumY += frame.ay_g;
    sumZ += frame.az_g;
    delay(sampleDelayMs);
  }

  AccelCalibration calibration;
  calibration.offsetX_g = sumX / calibrationSamples;
  calibration.offsetY_g = sumY / calibrationSamples;
  calibration.offsetZ_g = (sumZ / calibrationSamples) - 1.0;

  Serial.println("Accelerometer calibration complete");
  Serial.print("Accel X offset (g): ");
  Serial.println(calibration.offsetX_g, 6);
  Serial.print("Accel Y offset (g): ");
  Serial.println(calibration.offsetY_g, 6);
  Serial.print("Accel Z offset (g): ");
  Serial.println(calibration.offsetZ_g, 6);
  Serial.println();

  return calibration;
}