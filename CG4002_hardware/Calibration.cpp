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


  Serial.println();
  Serial.println("Keep sensor stationary...");
  Serial.println("Calibrating gyroscope...");


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


  Serial.println();
  Serial.println("Calibration complete");

  Serial.print("Gyro X bias: ");
  Serial.println(calibration.biasX);

  Serial.print("Gyro Y bias: ");
  Serial.println(calibration.biasY);

  Serial.print("Gyro Z bias: ");
  Serial.println(calibration.biasZ);

  Serial.println();


  return calibration;
}