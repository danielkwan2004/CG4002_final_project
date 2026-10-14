#include "SensorFrame.h"
#include "Calibration.h"
#include "LowPassFilter.h"
#include "ICM42686P.h"
#include "WiFiTelemetry.h"
#include "AxisMapping.h"
#include "MoveDetector.h"
#include "CaptureDiagnostics.h"
#include "TelemetryScheduler.h"
#include <esp_system.h>

const unsigned long SAMPLE_PERIOD_US = ImuConfig::SAMPLE_PERIOD_US;
const int BUFFER_SIZE = 256;
const int CALIBRATION_SAMPLES = 400;          // 2 seconds at 200 Hz
const int SAMPLE_DELAY_MS = 5;
const float FILTER_ALPHA = 0.2;
const uint8_t NODE_ID = 1;
const AxisMapping& NODE_AXIS_MAPPING = AXIS_MAPPING_IDENTITY;
const int I2C_SDA_PIN = 21;
const int I2C_SCL_PIN = 22;
const uint16_t I2C_TIMEOUT_MS = 5;
const int HAPTIC_PIN = 25;
const int HAPTIC_DUTY_ON = 255;  // module is only felt at duty >=200 on the bench
const bool ENABLE_WIFI_TELEMETRY = true;
const bool WIFI_ONLY_DEMO = false;
// P1/P2 capture: keep acquisition free of blocking per-sample UART output.
// All movement samples and periodic diagnostics are saved by the UDP receiver.
const bool ENABLE_VERBOSE_SAMPLE_LOG = false;
const char* WIFI_DEMO_SSID = "Reno13";
const char* WIFI_DEMO_PASSWORD = "12345678";
const char* WIFI_LAPTOP_IP = "10.123.219.93";
const uint16_t WIFI_DEMO_PORT = 4210;

unsigned long nextSampleTime;
uint32_t bootId = 0;
CaptureDiagnostics captureDiagnostics;
TelemetryScheduler telemetryScheduler;
unsigned long lastConfigReportMs = 0;


// =====================================================
// Gyroscope calibration data
// =====================================================

GyroCalibration gyroCalibration;
AccelCalibration accelCalibration;

// Placeholder start/end-of-move gate deciding when frames get sent (see
// MoveDetector.h) -- thresholds are not yet tuned against real actions.
MoveDetector moveDetector;


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
uint32_t lastConsumedSeq = 0;
bool hasConsumedSeq = false;
unsigned long sequenceGapCount = 0;

unsigned long lastProduceTime = 0;
long maxProducerJitterUs = 0;          // deviation from the 5 ms cadence

unsigned long maxConsumerQueueLatencyUs = 0;  // time a frame sat in the buffer
unsigned long maxConsumerProcessingUs = 0;    // processing + saturation check
unsigned long totalConsumerProcessingUs = 0;
unsigned long processedSampleCount = 0;
unsigned long saturatedSampleCount = 0;

// Maximum telemetry operation cost, including diagnostics, separate from sensing.
unsigned long maxWifiSendUs = 0;
unsigned long totalWifiSendUs = 0;
unsigned long wifiSendCount = 0;

const int SATURATION_THRESHOLD_COUNTS = 29490;  // 90% of int16 range

enum NodeState {
  NODE_BOOT,
  NODE_CALIBRATING,
  NODE_STREAMING,
  NODE_FAULT
};

NodeState nodeState = NODE_BOOT;
const char* faultReason = "none";
bool runtimeImuFault = false;
bool calibrationReadFailed = false;
unsigned long lastRecoveryMs = 0;
unsigned long lastImuErrorLogMs = 0;
ImuHealth imuHealth;

void printImuHealth();

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

// Non-blocking PWM waveform player: each pattern is a sequence of
// (duty, duration) steps, advanced from loop() via updateHapticPattern()
// without delay(). Other loop work can still extend the step durations.
struct HapticStep {
  uint8_t duty;
  uint16_t durationMs;
};

const HapticStep HAPTIC_STEPS_SINGLE_PULSE[] = {
  { HAPTIC_DUTY_ON, 150 },
};

const HapticStep HAPTIC_STEPS_DOUBLE_PULSE[] = {
  { HAPTIC_DUTY_ON, 150 },
  { 0, 250 },
  { HAPTIC_DUTY_ON, 150 },
};

// ERM motors need time to spin up, so short (~80ms) pulses barely register --
// each on-step here is as long as the single pulse to give it full strength.
const HapticStep HAPTIC_STEPS_FAULT_PATTERN[] = {
  { HAPTIC_DUTY_ON, 150 },
  { 0, 100 },
  { HAPTIC_DUTY_ON, 150 },
  { 0, 100 },
  { HAPTIC_DUTY_ON, 150 },
};

const HapticStep* hapticActiveSteps = nullptr;
uint8_t hapticStepCount = 0;
uint8_t hapticStepIndex = 0;
unsigned long hapticStepStartMs = 0;
bool hapticPatternRunning = false;

void triggerHapticPattern(HapticPattern pattern) {
  switch (pattern) {
    case HAPTIC_SINGLE_PULSE:
      hapticActiveSteps = HAPTIC_STEPS_SINGLE_PULSE;
      hapticStepCount = sizeof(HAPTIC_STEPS_SINGLE_PULSE) / sizeof(HapticStep);
      break;
    case HAPTIC_DOUBLE_PULSE:
      hapticActiveSteps = HAPTIC_STEPS_DOUBLE_PULSE;
      hapticStepCount = sizeof(HAPTIC_STEPS_DOUBLE_PULSE) / sizeof(HapticStep);
      break;
    case HAPTIC_FAULT_PATTERN:
    default:
      hapticActiveSteps = HAPTIC_STEPS_FAULT_PATTERN;
      hapticStepCount = sizeof(HAPTIC_STEPS_FAULT_PATTERN) / sizeof(HapticStep);
      break;
  }

  hapticStepIndex = 0;
  hapticStepStartMs = millis();
  hapticPatternRunning = true;
  analogWrite(HAPTIC_PIN, hapticActiveSteps[0].duty);

  Serial.print("[haptic] pattern=");
  Serial.println(hapticPatternName(pattern));
}

void updateHapticPattern() {
  if (!hapticPatternRunning) {
    return;
  }

  unsigned long elapsedMs = millis() - hapticStepStartMs;
  if (elapsedMs < hapticActiveSteps[hapticStepIndex].durationMs) {
    return;
  }

  hapticStepIndex++;
  if (hapticStepIndex >= hapticStepCount) {
    analogWrite(HAPTIC_PIN, 0);
    hapticPatternRunning = false;
    return;
  }

  hapticStepStartMs = millis();
  analogWrite(HAPTIC_PIN, hapticActiveSteps[hapticStepIndex].duty);
}

// Bench-test hook: '1'/'2'/'3' over Serial trigger a pattern directly.
// Real invocation from a received HAPTIC_CMD is Comms' job later.
void pollHapticTestCommand() {
  if (Serial.available() <= 0) {
    return;
  }

  char command = Serial.read();
  switch (command) {
    case '1': triggerHapticPattern(HAPTIC_SINGLE_PULSE); break;
    case '2': triggerHapticPattern(HAPTIC_DOUBLE_PULSE); break;
    case '3': triggerHapticPattern(HAPTIC_FAULT_PATTERN); break;
    case 'd': printImuHealth(); break;
    default: break;
  }
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
  return bufferCount >= 0 && bufferCount <= BUFFER_SIZE &&
      readIndex >= 0 && readIndex < BUFFER_SIZE &&
      writeIndex >= 0 && writeIndex < BUFFER_SIZE;
}

void enterFault(const char* reason, bool recoverable = false) {
  faultReason = reason;
  runtimeImuFault = recoverable;
  lastRecoveryMs = millis();
  Serial.printf("[fault] reason=%s automatic_recovery=%u\n", reason, recoverable);
  setNodeState(NODE_FAULT);
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
LowPassFilter filterAX;
LowPassFilter filterAY;
LowPassFilter filterAZ;

ICM42686P imu;
bool imuReadFault = false;  // Outcome of the latest read, not a permanent latch.
WiFiTelemetry wifiTelemetry;

void printImuHealth() {
  const ImuIoError& error = imu.lastError();
  Serial.printf("[imu-health] state=%s reason=%s seq=%lu failures=%lu consecutive=%lu max_consecutive=%lu attempts=%lu recoveries=%lu saturated=%lu stage=%s reg=0x%02X wire=%u bytes=%u/%u\n",
      nodeStateName(nodeState), faultReason, (unsigned long)nextSeq,
      (unsigned long)imuHealth.readFailures, (unsigned long)imuHealth.consecutive,
      (unsigned long)imuHealth.maxConsecutive, (unsigned long)imuHealth.recoveryAttempts,
      (unsigned long)imuHealth.recoveries, (unsigned long)imuHealth.saturated,
      error.stage, error.reg, error.wireStatus,
      (unsigned)error.received, (unsigned)error.expected);
}

void resetFilters() {
  filterGX.reset(); filterGY.reset(); filterGZ.reset();
  filterAX.reset(); filterAY.reset(); filterAZ.reset();
}

void recoverRuntimeImu() {
  if (!runtimeImuFault || millis() - lastRecoveryMs < ImuHealth::RECOVERY_INTERVAL_MS)
    return;
  ++imuHealth.recoveryAttempts;
  // This deliberately pauses acquisition while faulted. Never run calibration
  // on a moving sensor; retain the valid boot calibration at the same ranges.
  Wire.end();
  bool ready = Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, 400000);
  Wire.setTimeOut(I2C_TIMEOUT_MS);
  SensorFrame probe = {};
  ready = ready && imu.begin(Wire) && imu.readRaw(probe);
  lastRecoveryMs = millis();
  if (!ready) {
    printImuHealth();
    return;
  }
  ++imuHealth.recoveries;
  imuHealth.succeeded();
  imuReadFault = false;
  resetFilters();
  moveDetector = MoveDetector();
  runtimeImuFault = false;
  faultReason = "none";
  // Keep sequence and capture clocks continuous so the outage remains visible.
  // Keep nextSampleTime too: the scheduler counts expired outage slots once.
  setNodeState(NODE_STREAMING);
  Serial.println("[imu] recovered; retained boot calibration");
  printImuHealth();
}

SensorFrame readRealIMU() {
  SensorFrame frame = {};

  imuReadFault = !imu.readRaw(frame);
  if (imuReadFault) {
    if (nodeState == NODE_CALIBRATING) calibrationReadFailed = true;
  } else {
    applyAxisMapping(frame, NODE_AXIS_MAPPING);
  }

  return frame;
}

SensorFrame readSensor() {
  return readRealIMU();
}

void runWifiOnlyDemo() {
  static uint32_t demoSequence = 0;
  static unsigned long nextDemoSampleTime = 0;
  unsigned long currentTime = micros();

  if ((long)(currentTime - nextDemoSampleTime) < 0) {
    return;
  }

  nextDemoSampleTime += SAMPLE_PERIOD_US;

  SensorFrame frame = {};
  frame.timestamp_us = currentTime;
  frame.node_id = NODE_ID;
  frame.seq = demoSequence++;
  frame.ax = 0;
  frame.ay = 0;
  frame.az = 2048;
  frame.gx = static_cast<int16_t>((frame.seq % 40) - 20);
  frame.gy = 0;
  frame.gz = 0;
  frame.ax_g = 0.0;
  frame.ay_g = 0.0;
  frame.az_g = 1.0;
  frame.gx_dps = frame.gx / ImuConfig::GYRO_LSB_PER_DPS;
  frame.gy_dps = 0.0;
  frame.gz_dps = 0.0;
  frame.ax_filtered_g = frame.ax_g;
  frame.ay_filtered_g = frame.ay_g;
  frame.az_filtered_g = frame.az_g;
  frame.gx_filtered_dps = frame.gx_dps;
  frame.gy_filtered_dps = frame.gy_dps;
  frame.gz_filtered_dps = frame.gz_dps;
  frame.status_flags = SENSOR_STATUS_PHYSICAL_UNITS_VALID;

  frame.interval_us = SAMPLE_PERIOD_US;
  if (!wifiTelemetry.sendFrame(frame, bootId, 1, frame.seq)) {
    Serial.println("[wifi] demo send failed");
  }
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
  bootId = esp_random();
  captureDiagnostics.begin(NODE_ID, bootId);

  pinMode(HAPTIC_PIN, OUTPUT);
  analogWrite(HAPTIC_PIN, 0);

  if (WIFI_ONLY_DEMO) {
    if (!ENABLE_WIFI_TELEMETRY ||
        !wifiTelemetry.begin(WIFI_DEMO_SSID, WIFI_DEMO_PASSWORD,
                             WIFI_LAPTOP_IP, WIFI_DEMO_PORT)) {
      Serial.println("[wifi] demo begin failed");
      return;
    }

    Serial.print("[wifi] demo connected esp_ip=");
    Serial.print(wifiTelemetry.localIP());
    Serial.print(" gateway=");
    Serial.print(WiFi.gatewayIP());
    Serial.print(" laptop_ip=");
    Serial.println(WIFI_LAPTOP_IP);
    return;
  }

  if (ENABLE_WIFI_TELEMETRY &&
      !wifiTelemetry.begin(WIFI_DEMO_SSID, WIFI_DEMO_PASSWORD,
                           WIFI_LAPTOP_IP, WIFI_DEMO_PORT)) {
    Serial.println("[wifi] begin failed");
    enterFault("wifi_startup");
    return;
  }

  if (ENABLE_WIFI_TELEMETRY) {
    Serial.print("[wifi] hotspot connected ssid=");
    Serial.print(WIFI_DEMO_SSID);
    Serial.print(" esp_ip=");
    Serial.print(wifiTelemetry.localIP());
    Serial.print(" gateway=");
    Serial.print(WiFi.gatewayIP());
    Serial.print(" laptop_ip=");
    Serial.print(WIFI_LAPTOP_IP);
    Serial.print(" port=");
    Serial.println(WIFI_DEMO_PORT);
  }

  Serial.print("[state] ");
  Serial.println(nodeStateName(nodeState));
  if (!Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, 400000)) {
    enterFault("i2c_startup");
    return;
  }
  // One 12-byte read comfortably fits the 5 ms budget at 400 kHz.
  // Measured acquisition intervals, not this setting, establish the achieved rate.
  Wire.setClock(400000);
  Wire.setTimeOut(I2C_TIMEOUT_MS);
  if (!imu.begin(Wire, ICM42686P::DEFAULT_ADDRESS)) {
    Serial.println("[imu] begin/readback failed");
    enterFault("imu_startup_readback");
    printImuHealth();
    return;
  }
  Serial.println("[imu] ready; axis mapping=identity (provisional)");
  setNodeState(NODE_CALIBRATING);
  Serial.println("Keep sensor flat with +Z upward and still for BOTH calibrations (~4 s)...");
  if (ENABLE_WIFI_TELEMETRY) {
    captureDiagnostics.sendConfiguration(wifiTelemetry, imu.configuration(),
        gyroCalibration, accelCalibration, nodeStateName(nodeState),
        FILTER_ALPHA, CALIBRATION_SAMPLES);
  }

  gyroCalibration = calibrateGyroscope(
      readSensor,
      CALIBRATION_SAMPLES,
      SAMPLE_DELAY_MS
  );

    accelCalibration = calibrateAccelerometer(
      readSensor,
      CALIBRATION_SAMPLES,
      SAMPLE_DELAY_MS
    );

  if (!bufferStateIsValid() || calibrationReadFailed) {
    enterFault(calibrationReadFailed ? "calibration_read_failed" : "buffer_invariant");
    printImuHealth();
    return;
  }

  setNodeState(NODE_STREAMING);
  Serial.printf("[calibration] gyro bias counts=(%.6f,%.6f,%.6f)\n",
      gyroCalibration.biasX, gyroCalibration.biasY, gyroCalibration.biasZ);
  Serial.println("[imu] send d for health counters; 1/2/3 for haptic patterns");
  if (ENABLE_WIFI_TELEMETRY) {
    captureDiagnostics.sendConfiguration(wifiTelemetry, imu.configuration(),
        gyroCalibration, accelCalibration, nodeStateName(nodeState),
        FILTER_ALPHA, CALIBRATION_SAMPLES);
    lastConfigReportMs = millis();
  }

  if (ENABLE_VERBOSE_SAMPLE_LOG) {
  Serial.println(
  "Seq | "
  "AX [raw counts, calibrated g, filtered g] | "
  "AY [raw counts, calibrated g, filtered g] | "
  "AZ [raw counts, calibrated g, filtered g] | "
  "GX [raw counts, corrected counts, filtered counts, filtered dps] | "
  "GY [raw counts, corrected counts, filtered counts, filtered dps] | "
  "GZ [raw counts, corrected counts, filtered counts, filtered dps] | "
  "status_flags"
  );
  }

  nextSampleTime = micros();
  nextStatsPrintTime = micros() + STATS_PRINT_INTERVAL_US;
}

// Called only inside an admitted telemetry slot, including while in FAULT.
// The periodic trigger queues work; it never sends a whole heartbeat at once.
bool publishCaptureDiagnostics() {
  captureDiagnostics.recordImuHealth(imuHealth);
  unsigned long reportTime = micros();
  if ((long)(reportTime - nextStatsPrintTime) >= 0) {
    bool includeConfiguration = millis() - lastConfigReportMs >= 5000 || nodeState == NODE_FAULT;
    if (captureDiagnostics.requestHeartbeat(includeConfiguration)) {
      nextStatsPrintTime = reportTime + STATS_PRINT_INTERVAL_US;
      if (includeConfiguration) lastConfigReportMs = millis();
      maxProducerJitterUs = 0;
      maxConsumerQueueLatencyUs = 0;
      totalConsumerProcessingUs = 0;
      processedSampleCount = 0;
      saturatedSampleCount = 0;
      sequenceGapCount = 0;
      totalWifiSendUs = 0;
      wifiSendCount = 0;
      // Processing/telemetry maxima are now retained for the whole boot.
    }
  }
  return captureDiagnostics.serviceHeartbeat(wifiTelemetry, reportTime,
      nodeStateName(nodeState), droppedSampleCount, bufferHighWaterMark,
      maxConsumerProcessingUs, maxWifiSendUs, imu.configuration(),
      gyroCalibration, accelCalibration, FILTER_ALPHA, CALIBRATION_SAMPLES);
}

void serviceTelemetry() {
  if (!ENABLE_WIFI_TELEMETRY || !telemetryScheduler.takeSlot(micros(),
      nextSampleTime, nextSeq, nodeState != NODE_FAULT)) return;
  unsigned long startUs = micros();
  bool diagnostic = captureDiagnostics.publishFinalBurst(wifiTelemetry);
  if (!diagnostic) diagnostic = publishCaptureDiagnostics();
  if (!diagnostic) wifiTelemetry.service(captureDiagnostics);
  unsigned long durationUs = micros() - startUs;
  if (durationUs > maxWifiSendUs) maxWifiSendUs = durationUs;
  captureDiagnostics.recordTelemetryCost(durationUs, diagnostic);
}


// =====================================================
// Main loop
// =====================================================

void loop() {

  if (WIFI_ONLY_DEMO) {
    runWifiOnlyDemo();
    return;
  }

  pollHapticTestCommand();
  updateHapticPattern();

  if (nodeState == NODE_FAULT) {
    serviceTelemetry();
    recoverRuntimeImu();
    return;
  }

  unsigned long currentTime = micros();


  // ---------------------------------------------------
  // Producer: acquire sensor data at 200 Hz
  // ---------------------------------------------------

  if ((long)(currentTime - nextSampleTime) >= 0) {

    if (!bufferStateIsValid()) {
      enterFault("buffer_invariant");
      return;
    }

    unsigned long latenessUs = currentTime - nextSampleTime;
    uint32_t skipped = latenessUs / SAMPLE_PERIOD_US;
    // Skip expired software slots. Catch-up reads cannot recover overwritten
    // IMU registers and could instead count the same sensor update twice.
    nextSampleTime += (skipped + 1) * SAMPLE_PERIOD_US;

    // Producer jitter: deviation from the expected 5 ms cadence.
    if (lastProduceTime != 0) {
      long jitterUs = (long)(currentTime - lastProduceTime) - (long)SAMPLE_PERIOD_US;
      if (abs(jitterUs) > abs(maxProducerJitterUs)) {
        maxProducerJitterUs = jitterUs;
      }
    }
    lastProduceTime = currentTime;

    unsigned long readStart = micros();
    SensorFrame frame = readSensor();
    unsigned long readUs = micros() - readStart;

    if (imuReadFault) {
      captureDiagnostics.recordMissedAcquisition(readUs, latenessUs, skipped);
      moveDetector.interruptQuietWindow();
      bool sustained = imuHealth.failed();
      if (imuHealth.readFailures == 1 || millis() - lastImuErrorLogMs >= 1000 || sustained) {
        lastImuErrorLogMs = millis();
        printImuHealth();
      }
      if (sustained) {
        // Close accounting with an explicit interruption, not a fabricated
        // quiet/end sample. Already queued real samples may still drain.
        captureDiagnostics.endBurst(wifiTelemetry, true);
        moveDetector = MoveDetector();
        enterFault("imu_read_outage", true);
      }
      return;
    }
    imuHealth.succeeded();
    frame.node_id = NODE_ID;
    frame.seq = nextSeq++;
    frame.interval_us = captureDiagnostics.recordAcquisition(
        frame.timestamp_us, readUs, latenessUs, skipped);
    frame.ax_g -= accelCalibration.offsetX_g;
    frame.ay_g -= accelCalibration.offsetY_g;
    frame.az_g -= accelCalibration.offsetZ_g;
  
    if (!addToBuffer(frame)) {
      droppedSampleCount++;
    }

    if (bufferCount > bufferHighWaterMark) {
      bufferHighWaterMark = bufferCount;
    }

    if (!bufferStateIsValid()) {
      enterFault("buffer_invariant");
      return;
    }
  }


  // ---------------------------------------------------
  // Consumer
  // ---------------------------------------------------

  SensorFrame frame;

  if (readFromBuffer(frame)) {

    unsigned long consumeStart = micros();

    if (hasConsumedSeq && frame.seq != lastConsumedSeq + 1) {
      sequenceGapCount += frame.seq > lastConsumedSeq
                              ? frame.seq - lastConsumedSeq - 1
                              : 1;
    }
    lastConsumedSeq = frame.seq;
    hasConsumedSeq = true;

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

    float filteredAX =
      filterAX.update(frame.ax_g, FILTER_ALPHA);

    float filteredAY =
      filterAY.update(frame.ay_g, FILTER_ALPHA);

    float filteredAZ =
      filterAZ.update(frame.az_g, FILTER_ALPHA);

    frame.ax_filtered_g = filteredAX;
    frame.ay_filtered_g = filteredAY;
    frame.az_filtered_g = filteredAZ;
    frame.gx_filtered_dps = filteredGX / ImuConfig::GYRO_LSB_PER_DPS;
    frame.gy_filtered_dps = filteredGY / ImuConfig::GYRO_LSB_PER_DPS;
    frame.gz_filtered_dps = filteredGZ / ImuConfig::GYRO_LSB_PER_DPS;
    frame.status_flags |= SENSOR_STATUS_CALIBRATED;

    bool sampleSaturated =
        axisIsSaturated(frame.ax) ||
        axisIsSaturated(frame.ay) ||
        axisIsSaturated(frame.az) ||
        axisIsSaturated(frame.gx) ||
        axisIsSaturated(frame.gy) ||
        axisIsSaturated(frame.gz);
    if (sampleSaturated) {
      frame.status_flags |= SENSOR_STATUS_SATURATED;
      saturatedSampleCount++;
      ++imuHealth.saturated;
    }

    // -----------------------------
    // Start/end-of-move gating (placeholder -- see MoveDetector.h)
    // -----------------------------

    float gyroMagDps = sqrtf(
        frame.gx_filtered_dps * frame.gx_filtered_dps +
        frame.gy_filtered_dps * frame.gy_filtered_dps +
        frame.gz_filtered_dps * frame.gz_filtered_dps);
    float accelMagG = sqrtf(
        frame.ax_filtered_g * frame.ax_filtered_g +
        frame.ay_filtered_g * frame.ay_filtered_g +
        frame.az_filtered_g * frame.az_filtered_g);
    float accelDeviationG = fabsf(accelMagG - 1.0f);

    bool wasMoveActive = moveDetector.isActive();
    MoveEvent moveEvent = moveDetector.update(gyroMagDps, accelDeviationG, millis());
    bool isMoveActiveNow = moveDetector.isActive();

    if (moveEvent == MOVE_EVENT_STARTED) {
      captureDiagnostics.startBurst(frame);
      if (ENABLE_VERBOSE_SAMPLE_LOG) {
        Serial.print("[move] start seq=");
        Serial.println(frame.seq);
      }
    } else if (moveEvent == MOVE_EVENT_ENDED) {
      if (ENABLE_VERBOSE_SAMPLE_LOG) {
        Serial.print("[move] end seq=");
        Serial.println(frame.seq);
      }
    }

    // Send the boundary frame on either side of a transition too, so the
    // receiver sees the sample that actually crossed the threshold.
    bool shouldSendFrame = wasMoveActive || isMoveActiveNow;
    if (shouldSendFrame) {
      frame.status_flags |= SENSOR_STATUS_MOVE_ACTIVE;
    } else {
      captureDiagnostics.recordIdle(frame, gyroCalibration);
    }

    // Excludes the Serial prints below.
    unsigned long processingUs = micros() - consumeStart;
    if (processingUs > maxConsumerProcessingUs) {
      maxConsumerProcessingUs = processingUs;
    }
    totalConsumerProcessingUs += processingUs;
    processedSampleCount++;

    // -----------------------------
    // Print raw, calibrated, and filtered values for bench validation.
    // Gated on shouldSendFrame -- printing every idle sample at 200Hz over
    // 115200 baud was the real bottleneck throttling the whole consumer
    // loop well below the nominal sample rate.
    // -----------------------------

    if (ENABLE_VERBOSE_SAMPLE_LOG && shouldSendFrame) {

    Serial.print(frame.seq);
    Serial.print(" | ");

    Serial.print(frame.ax);
    Serial.print(",");
    Serial.print(frame.ax_g, 4);
    Serial.print(",");
    Serial.print(frame.ax_filtered_g, 4);
    Serial.print(" | ");

    Serial.print(frame.ay);
    Serial.print(",");
    Serial.print(frame.ay_g, 4);
    Serial.print(",");
    Serial.print(frame.ay_filtered_g, 4);
    Serial.print(" | ");

    Serial.print(frame.az);
    Serial.print(",");
    Serial.print(frame.az_g, 4);
    Serial.print(",");
    Serial.print(frame.az_filtered_g, 4);
    Serial.print(" | ");

    Serial.print(frame.gx);
    Serial.print(",");

    Serial.print(correctedGX);
    Serial.print(",");

    Serial.print(filteredGX);
    Serial.print(",");
    Serial.print(frame.gx_filtered_dps, 4);

    Serial.print(" | ");

    Serial.print(frame.gy);
    Serial.print(",");

    Serial.print(correctedGY);
    Serial.print(",");

    Serial.print(filteredGY);
    Serial.print(",");
    Serial.print(frame.gy_filtered_dps, 4);

    Serial.print(" | ");

    Serial.print(frame.gz);
    Serial.print(",");

    Serial.print(correctedGZ);
    Serial.print(",");

    Serial.print(filteredGZ);
    Serial.print(",");
    Serial.print(frame.gz_filtered_dps, 4);
    Serial.print(" | status=");
    Serial.println(frame.status_flags);

    }

    if (ENABLE_WIFI_TELEMETRY && shouldSendFrame) {
      unsigned long wifiSendStart = micros();
      bool sendOk = wifiTelemetry.enqueueFrame(frame, bootId,
          captureDiagnostics.burstId(), captureDiagnostics.burstIndex());
      captureDiagnostics.recordQueued(frame, sendOk);
      unsigned long wifiSendUs = micros() - wifiSendStart;
      if (wifiSendUs > maxWifiSendUs) {
        maxWifiSendUs = wifiSendUs;
      }
      totalWifiSendUs += wifiSendUs;
      wifiSendCount++;
      if (!sendOk && ENABLE_VERBOSE_SAMPLE_LOG) {
        Serial.println("[wifi] transmit queue full; sample discarded");
      }
      if (moveEvent == MOVE_EVENT_ENDED) {
        captureDiagnostics.endBurst(wifiTelemetry);
      }
    }
  }


  // At most one network operation per acquisition, with >3.5 ms remaining.
  // Heartbeat parts are >=10 ms apart, leaving slots for movement delivery.
  serviceTelemetry();
}
