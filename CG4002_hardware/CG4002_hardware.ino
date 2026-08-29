#include "SensorFrame.h"
#include "Calibration.h"
#include "LowPassFilter.h"

const unsigned long SAMPLE_PERIOD_US = 5000;  // 200 Hz
const int BUFFER_SIZE = 256;
const int CALIBRATION_SAMPLES = 400;          // 2 seconds at 200 Hz
const int SAMPLE_DELAY_MS = 5;
const float FILTER_ALPHA = 0.2;

unsigned long nextSampleTime;


// =====================================================
// Gyroscope calibration data
// =====================================================

GyroCalibration gyroCalibration;


// =====================================================
// Circular buffer
// =====================================================

SensorFrame sensorBuffer[BUFFER_SIZE];

int writeIndex = 0;
int readIndex = 0;
int bufferCount = 0;

// =====================================================
// Low-pass filters for gyroscope
// =====================================================

LowPassFilter filterGX;
LowPassFilter filterGY;
LowPassFilter filterGZ;


// =====================================================
// Fake IMU
// =====================================================

SensorFrame readFakeIMU() {

  SensorFrame frame;

  frame.timestamp_us = micros();

  // Fake accelerometer data
  frame.ax = random(-1000, 1000);
  frame.ay = random(-1000, 1000);
  frame.az = random(-1000, 1000);

  /*
     Simulated gyro biases:

     X = +120
     Y = -80
     Z = +45

     Small random noise is added around each value.
  */

  frame.gx = 120 + random(-10, 11);
  frame.gy = -80 + random(-10, 11);
  frame.gz = 45 + random(-10, 11);

  return frame;
}


// =====================================================
// Buffer functions
// =====================================================

bool addToBuffer(const SensorFrame& frame) {

  if (bufferCount >= BUFFER_SIZE) {
    return false;
  }

  sensorBuffer[writeIndex] = frame;

  writeIndex++;

  if (writeIndex >= BUFFER_SIZE) {
    writeIndex = 0;
  }

  bufferCount++;

  return true;
}


bool readFromBuffer(SensorFrame& frame) {

  if (bufferCount == 0) {
    return false;
  }

  frame = sensorBuffer[readIndex];

  readIndex++;

  if (readIndex >= BUFFER_SIZE) {
    readIndex = 0;
  }

  bufferCount--;

  return true;
}


// =====================================================
// Setup
// =====================================================

void setup() {

  Serial.begin(115200);
  delay(1000);

  Serial.println("FireBeetle started");

  randomSeed(micros());

  gyroCalibration = calibrateGyroscope(
      readFakeIMU,
      CALIBRATION_SAMPLES,
      SAMPLE_DELAY_MS
  );

  Serial.println(
  "Raw GX, Corrected GX, Filtered GX | "
  "Raw GY, Corrected GY, Filtered GY | "
  "Raw GZ, Corrected GZ, Filtered GZ"
  );

  nextSampleTime = micros();
}


// =====================================================
// Main loop
// =====================================================

void loop() {

  unsigned long currentTime = micros();


  // ---------------------------------------------------
  // Producer: acquire sensor data at 200 Hz
  // ---------------------------------------------------

  if ((long)(currentTime - nextSampleTime) >= 0) {

    nextSampleTime += SAMPLE_PERIOD_US;

    SensorFrame frame = readFakeIMU();

    addToBuffer(frame);
  }


  // ---------------------------------------------------
  // Consumer
  // ---------------------------------------------------

  SensorFrame frame;

  if (readFromBuffer(frame)) {

    // -----------------------------
    // Bias correction
    // -----------------------------

    float correctedGX =
        frame.gx - gyroCalibration.biasX;

    float correctedGY =
        frame.gy - gyroCalibration.biasY;

    float correctedGZ =
        frame.gz - gyroCalibration.biasZ;


    // -----------------------------
    // Low-pass filtering
    // -----------------------------

    float filteredGX =
        filterGX.update(correctedGX, FILTER_ALPHA);

    float filteredGY =
        filterGY.update(correctedGY, FILTER_ALPHA);

    float filteredGZ =
        filterGZ.update(correctedGZ, FILTER_ALPHA);


    // -----------------------------
    // Print raw vs corrected vs filtered
    // -----------------------------

    Serial.print(frame.gx);
    Serial.print(",");

    Serial.print(correctedGX);
    Serial.print(",");

    Serial.print(filteredGX);

    Serial.print(" | ");

    Serial.print(frame.gy);
    Serial.print(",");

    Serial.print(correctedGY);
    Serial.print(",");

    Serial.print(filteredGY);

    Serial.print(" | ");

    Serial.print(frame.gz);
    Serial.print(",");

    Serial.print(correctedGZ);
    Serial.print(",");

    Serial.println(filteredGZ);
  }
}