#include "SensorFrame.h"
#include "Calibration.h"
#include "LowPassFilter.h"
#include "ICM42686P.h"

const unsigned long SAMPLE_PERIOD_US = 5000;  // 200 Hz
const int BUFFER_SIZE = 256;
const int CALIBRATION_SAMPLES = 400;          // 2 seconds at 200 Hz
const int SAMPLE_DELAY_MS = 5;
const float FILTER_ALPHA = 0.2;
const uint8_t NODE_ID = 1;
const int I2C_SDA_PIN = 21;
const int I2C_SCL_PIN = 22;

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

// Occupancy diagnostics (Phase B.2): counts samples lost to a full
// buffer, and the highest bufferCount ever observed.
unsigned long droppedSampleCount = 0;
int bufferHighWaterMark = 0;

const unsigned long STATS_PRINT_INTERVAL_US = 1000000;  // 1 second
unsigned long nextStatsPrintTime;

// Sequencing + timing diagnostics (Phase B.3).
uint32_t nextSeq = 0;

unsigned long lastProduceTime = 0;
long maxProducerJitterUs = 0;          // deviation from the 5 ms cadence

unsigned long maxConsumerQueueLatencyUs = 0;  // time a frame sat in the buffer
unsigned long maxConsumerProcessingUs = 0;    // processing + saturation check
unsigned long totalConsumerProcessingUs = 0;
unsigned long processedSampleCount = 0;
unsigned long saturatedSampleCount = 0;

const int SATURATION_THRESHOLD_COUNTS = 29490;  // 90% of int16 range

enum NodeState {
  NODE_BOOT,
  NODE_CALIBRATING,
  NODE_STREAMING,
  NODE_FAULT
};

NodeState nodeState = NODE_BOOT;

enum HapticPattern {
  HAPTIC_SINGLE_PULSE,
  HAPTIC_DOUBLE_PULSE,
  HAPTIC_FAULT_PATTERN
};

const char* hapticPatternName(HapticPattern pattern) {
  switch (pattern) {
    case HAPTIC_SINGLE_PULSE: return "SINGLE_PULSE";
    case HAPTIC_DOUBLE_PULSE: return "DOUBLE_PULSE";
    case HAPTIC_FAULT_PATTERN: return "FAULT_PATTERN";
    default: return "UNKNOWN";
  }
}

void triggerHapticPattern(HapticPattern pattern) {
  Serial.print("[haptic] stub pattern=");
  Serial.println(hapticPatternName(pattern));
}

const char* nodeStateName(NodeState state) {
  switch (state) {
    case NODE_BOOT: return "BOOT";
    case NODE_CALIBRATING: return "CALIBRATING";
    case NODE_STREAMING: return "STREAMING";
    case NODE_FAULT: return "FAULT";
    default: return "UNKNOWN";
  }
}

void setNodeState(NodeState nextState) {
  if (nodeState == nextState) {
    return;
  }

  nodeState = nextState;
  Serial.print("[state] ");
  Serial.println(nodeStateName(nodeState));
}

bool bufferStateIsValid() {
  return bufferCount >= 0 && bufferCount <= BUFFER_SIZE;
}

bool axisIsSaturated(int16_t value) {
  int32_t magnitude = value;
  if (magnitude < 0) {
    magnitude = -magnitude;
  }
  return magnitude >= SATURATION_THRESHOLD_COUNTS;
}

// =====================================================
// Low-pass filters for gyroscope
// =====================================================

LowPassFilter filterGX;
LowPassFilter filterGY;
LowPassFilter filterGZ;

ICM42686P imu;
bool imuReadFault = false;

SensorFrame readRealIMU() {
  SensorFrame frame = {};

  if (!imu.readRaw(frame)) {
    imuReadFault = true;
  }

  return frame;
}

SensorFrame readSensor() {
  return readRealIMU();
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

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);

  if (!imu.begin(Wire, ICM42686P::DEFAULT_ADDRESS)) {
    Serial.println("[imu] begin failed");
    setNodeState(NODE_FAULT);
    return;
  }

  Serial.println("[imu] ready");

  Serial.print("[state] ");
  Serial.println(nodeStateName(nodeState));
  setNodeState(NODE_CALIBRATING);

  gyroCalibration = calibrateGyroscope(
      readSensor,
      CALIBRATION_SAMPLES,
      SAMPLE_DELAY_MS
  );

  if (!bufferStateIsValid() || imuReadFault) {
    setNodeState(NODE_FAULT);
    return;
  }

  setNodeState(NODE_STREAMING);

  Serial.println(
  "Seq | "
  "Raw GX, Corrected GX, Filtered GX, GX dps | "
  "Raw GY, Corrected GY, Filtered GY, GY dps | "
  "Raw GZ, Corrected GZ, Filtered GZ, GZ dps"
  );

  nextSampleTime = micros();
  nextStatsPrintTime = micros();
}


// =====================================================
// Main loop
// =====================================================

void loop() {

  if (nodeState == NODE_FAULT) {
    return;
  }

  unsigned long currentTime = micros();


  // ---------------------------------------------------
  // Producer: acquire sensor data at 200 Hz
  // ---------------------------------------------------

  if ((long)(currentTime - nextSampleTime) >= 0) {

    if (!bufferStateIsValid()) {
      setNodeState(NODE_FAULT);
      return;
    }

    nextSampleTime += SAMPLE_PERIOD_US;

    // Producer jitter: deviation from the expected 5 ms cadence.
    if (lastProduceTime != 0) {
      long jitterUs = (long)(currentTime - lastProduceTime) - (long)SAMPLE_PERIOD_US;
      if (abs(jitterUs) > abs(maxProducerJitterUs)) {
        maxProducerJitterUs = jitterUs;
      }
    }
    lastProduceTime = currentTime;

    SensorFrame frame = readSensor();

    if (imuReadFault) {
      setNodeState(NODE_FAULT);
      return;
    }
    frame.node_id = NODE_ID;
    frame.seq = nextSeq++;
  
    if (!addToBuffer(frame)) {
      droppedSampleCount++;
    }

    if (bufferCount > bufferHighWaterMark) {
      bufferHighWaterMark = bufferCount;
    }

    if (!bufferStateIsValid()) {
      setNodeState(NODE_FAULT);
      return;
    }
  }


  // ---------------------------------------------------
  // Consumer
  // ---------------------------------------------------

  SensorFrame frame;

  if (readFromBuffer(frame)) {

    unsigned long consumeStart = micros();

    // Queue latency: how long this frame sat in the buffer before being
    // consumed -- distinct from processing time below.
    unsigned long queueLatencyUs = consumeStart - frame.timestamp_us;
    if (queueLatencyUs > maxConsumerQueueLatencyUs) {
      maxConsumerQueueLatencyUs = queueLatencyUs;
    }

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

    bool sampleSaturated =
        axisIsSaturated(frame.ax) ||
        axisIsSaturated(frame.ay) ||
        axisIsSaturated(frame.az) ||
        axisIsSaturated(frame.gx) ||
        axisIsSaturated(frame.gy) ||
        axisIsSaturated(frame.gz);
    if (sampleSaturated) {
      saturatedSampleCount++;
    }

    // Excludes the Serial prints below.
    unsigned long processingUs = micros() - consumeStart;
    if (processingUs > maxConsumerProcessingUs) {
      maxConsumerProcessingUs = processingUs;
    }
    totalConsumerProcessingUs += processingUs;
    processedSampleCount++;

    // -----------------------------
    // Print raw vs corrected vs filtered
    // -----------------------------

    Serial.print(frame.seq);
    Serial.print(" | ");

    Serial.print(frame.gx);
    Serial.print(",");

    Serial.print(correctedGX);
    Serial.print(",");

    Serial.print(filteredGX);
    Serial.print(",");
    Serial.print(frame.gx_dps);

    Serial.print(" | ");

    Serial.print(frame.gy);
    Serial.print(",");

    Serial.print(correctedGY);
    Serial.print(",");

    Serial.print(filteredGY);
    Serial.print(",");
    Serial.print(frame.gy_dps);

    Serial.print(" | ");

    Serial.print(frame.gz);
    Serial.print(",");

    Serial.print(correctedGZ);
    Serial.print(",");

    Serial.print(filteredGZ);
    Serial.print(",");
    Serial.println(frame.gz_dps);
  }


  // ---------------------------------------------------
  // Occupancy diagnostics: printed periodically, not per-sample.
  // Placed after the consumer so this slower, infrequent print doesn't
  // inflate this iteration's measured queue latency/processing time.
  // ---------------------------------------------------

  if ((long)(currentTime - nextStatsPrintTime) >= 0) {

    nextStatsPrintTime += STATS_PRINT_INTERVAL_US;

    Serial.print("[stats] state=");
    Serial.print(nodeStateName(nodeState));
    Serial.print(" dropped=");
    Serial.print(droppedSampleCount);
    Serial.print(" highWaterMark=");
    Serial.print(bufferHighWaterMark);
    Serial.print("/");
    Serial.print(BUFFER_SIZE);
    Serial.print(" maxProducerJitterUs=");
    Serial.print(maxProducerJitterUs);
    Serial.print(" maxQueueLatencyUs=");
    Serial.print(maxConsumerQueueLatencyUs);
    Serial.print(" maxProcessingUs=");
    Serial.print(maxConsumerProcessingUs);
    Serial.print(" avgProcessingUs=");
    unsigned long averageProcessingUs = 0;
    if (processedSampleCount > 0) {
      averageProcessingUs = totalConsumerProcessingUs / processedSampleCount;
    }
    Serial.print(averageProcessingUs);
    Serial.print(" cpuMarginUs=");
    long cpuMarginUs = (long)SAMPLE_PERIOD_US - (long)maxConsumerProcessingUs;
    Serial.print(cpuMarginUs);
    Serial.print(" saturatedSamples=");
    Serial.println(saturatedSampleCount);

    // Report worst-case-per-second, not worst-case-since-boot.
    maxProducerJitterUs = 0;
    maxConsumerQueueLatencyUs = 0;
    maxConsumerProcessingUs = 0;
    totalConsumerProcessingUs = 0;
    processedSampleCount = 0;
    saturatedSampleCount = 0;
  }
}