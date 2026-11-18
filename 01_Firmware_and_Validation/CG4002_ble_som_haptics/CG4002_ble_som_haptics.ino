#include "ICM42686P.h"
#include "Calibration.h"
#include "AxisMapping.h"
#include "LowPassFilter.h"
#include "LocalMotion.h"
#include "ImuHealth.h"
#include "Haptics.h"
#include "BleProtocol.h"

// Arduino builds this tab together with BLE.ino. The transport uses the
// supplied client protocol; this tab owns calibration, filtering and movement.
constexpr uint8_t SENSOR_NODE_ID = NodeConfig::ACTIVE.id;
constexpr int SDA_PIN = 21, SCL_PIN = 22;
constexpr uint16_t I2C_TIMEOUT_MS = 5;
constexpr int CALIBRATION_SAMPLES = 400;
constexpr float FILTER_ALPHA = 0.2f;
constexpr uint32_t PERIOD_US = ImuConfig::SAMPLE_PERIOD_US;
const AxisMapping& NODE_AXIS_MAPPING = AXIS_MAPPING_IDENTITY;

enum NodeState { BOOT, CALIBRATING, STREAMING, FAULT };
NodeState nodeState = BOOT;
const char* faultReason = "none";
ICM42686P imu;
ImuHealth health;
GyroCalibration gyroCalibration = {};
AccelCalibration accelCalibration = {};
LowPassFilter filters[6];
LocalMotion motionGate;
bool readFailed = false, calibrationFailed = false, recoverable = false;
uint32_t sequence = 0, burst = 0, nextSampleUs = 0;
uint32_t lastRecoveryMs = 0, lastErrorLogMs = 0;
uint32_t previousReadUs = 0, skippedSlots = 0, minDtUs = UINT32_MAX, maxDtUs = 0;
uint32_t maxReadUs = 0, maxServiceUs = 0;
uint64_t intervalSumUs = 0;
SensorFrame latestFrame = {};
uint32_t sampleTimestampMs = 0;

const char* stateName() {
  switch (nodeState) {
    case BOOT: return "BOOT";
    case CALIBRATING: return "CALIBRATING";
    case STREAMING: return "STREAMING";
    default: return "FAULT";
  }
}
void setState(NodeState state) {
  nodeState = state;
  Serial.printf("[state] %s reason=%s\n", stateName(), faultReason);
}
void enterFault(const char* reason, bool retry) {
  faultReason = reason; recoverable = retry; lastRecoveryMs = millis();
  motionGate.suspend();
  setState(FAULT);
}
void printHealth() {
  const auto& e = imu.lastError();
  Serial.printf("[health] state=%s seq=%lu active=%u failures=%lu consecutive=%lu recoveries=%lu saturated=%lu stage=%s reg=0x%02X wire=%u bytes=%u/%u\n",
      stateName(), (unsigned long)sequence, motionGate.open,
      (unsigned long)health.readFailures, (unsigned long)health.consecutive,
      (unsigned long)health.recoveries, (unsigned long)health.saturated,
      e.stage, e.reg, e.wireStatus, (unsigned)e.received, (unsigned)e.expected);
  Serial.printf("[timing] skipped=%lu max_read_us=%lu max_ble_service_us=%lu\n",
      (unsigned long)skippedSlots, (unsigned long)maxReadUs, (unsigned long)maxServiceUs);
  const auto& t=motionGate.detector.thresholds;
  Serial.printf("[motion] role=%s armed=%u reference_attempts=%lu reference_failures=%lu state=%u starts=%lu ends=%lu selected=%lu fallback=%lu invalid_excluded=%lu thresholds[g/a start,stop]=%.6f/%.6f,%.6f/%.6f\n",
      NODE_ID,motionGate.armed(),(unsigned long)motionGate.referenceAttempts,
      (unsigned long)motionGate.referenceFailures,unsigned(motionGate.detector.state),
      (unsigned long)motionGate.started,(unsigned long)motionGate.ended,
      (unsigned long)motionGate.selected,(unsigned long)motionGate.fallback,
      (unsigned long)motionGate.excludedInvalid,t.gyroStart,t.accelStart,t.gyroStop,t.accelStop);
}
SensorFrame readSensor() {
  SensorFrame f = {};
  readFailed = !imu.readRaw(f);
  if (readFailed) {
    if (nodeState == CALIBRATING) calibrationFailed = true;
  } else applyAxisMapping(f, NODE_AXIS_MAPPING);
  return f;
}
void setupSensor() {
  delay(1000);
  beginHaptics();
  if (!Wire.begin(SDA_PIN, SCL_PIN, 400000)) {
    enterFault("i2c_startup", false); return;
  }
  Wire.setTimeOut(I2C_TIMEOUT_MS);
  if (!imu.begin(Wire)) {
    enterFault("imu_startup", false); printHealth(); return;
  }
  setState(CALIBRATING);
  Serial.println("Keep supported and still through gyro calibration (~2 s). Stored per-sensor accelerometer calibration is used.");
  gyroCalibration = calibrateGyroscope(readSensor, CALIBRATION_SAMPLES, 5);
  accelCalibration = fixedAccelerometerCalibration();
  if (calibrationFailed) {
    enterFault("calibration_read_failed", false); printHealth(); return;
  }
  setState(STREAMING);
  Serial.printf("[calibration] gyro bias counts=(%.6f,%.6f,%.6f)\n",
      gyroCalibration.biasX, gyroCalibration.biasY, gyroCalibration.biasZ);
  Serial.println("[serial] d=health; 1/2/3=haptic patterns");
  nextSampleUs = micros();
}
void recoverImu() {
  if (!recoverable || millis()-lastRecoveryMs < ImuHealth::RECOVERY_INTERVAL_MS) return;
  ++health.recoveryAttempts;
  Wire.end();
  bool ready = Wire.begin(SDA_PIN, SCL_PIN, 400000);
  Wire.setTimeOut(I2C_TIMEOUT_MS);
  SensorFrame probe = {};
  ready = ready && imu.begin(Wire) && imu.readRaw(probe);
  lastRecoveryMs = millis();
  if (!ready) { printHealth(); return; }
  ++health.recoveries; health.succeeded();
  for (auto& filter : filters) filter.reset();
  readFailed = false; recoverable = false; faultReason = "none";
  setState(STREAMING);  // retain boot calibration, even if currently moving
  printHealth();
}
bool saturated(int16_t raw) {
  int32_t value = raw;
  return (value < 0 ? -value : value) >= 29490;
}
void acquireAndProcess(uint32_t now) {
  uint32_t skipped = (now-nextSampleUs) / PERIOD_US;
  skippedSlots += skipped;
  nextSampleUs += (skipped+1) * PERIOD_US;
  const uint32_t started = micros();
  SensorFrame f = readSensor();
  uint32_t cost = micros()-started;
  if (cost > maxReadUs) maxReadUs = cost;
  if (readFailed) {
    motionGate.features.invalidate(); motionGate.detector.interrupt();
    bool sustained = health.failed();
    if (health.readFailures == 1 || millis()-lastErrorLogMs >= 1000 || sustained) {
      lastErrorLogMs = millis(); printHealth();
    }
    if (sustained) enterFault("imu_read_outage", true);
    return;
  }
  health.succeeded();
  f.node_id = SENSOR_NODE_ID; f.seq = sequence++;
  f.interval_us = f.seq ? static_cast<uint32_t>(f.timestamp_us-previousReadUs) : 0;
  previousReadUs = f.timestamp_us;
  if (f.seq) {
    intervalSumUs += f.interval_us;
    if (f.interval_us < minDtUs) minDtUs = f.interval_us;
    if (f.interval_us > maxDtUs) maxDtUs = f.interval_us;
  }
  applyAccelerometerCalibration(f, accelCalibration);
  f.ax_filtered_g = filters[0].update(f.ax_g, FILTER_ALPHA);
  f.ay_filtered_g = filters[1].update(f.ay_g, FILTER_ALPHA);
  f.az_filtered_g = filters[2].update(f.az_g, FILTER_ALPHA);
  f.gx_filtered_dps = filters[3].update(f.gx-gyroCalibration.biasX, FILTER_ALPHA) / ImuConfig::GYRO_LSB_PER_DPS;
  f.gy_filtered_dps = filters[4].update(f.gy-gyroCalibration.biasY, FILTER_ALPHA) / ImuConfig::GYRO_LSB_PER_DPS;
  f.gz_filtered_dps = filters[5].update(f.gz-gyroCalibration.biasZ, FILTER_ALPHA) / ImuConfig::GYRO_LSB_PER_DPS;
  f.status_flags |= SENSOR_STATUS_CALIBRATED;
  if (saturated(f.ax) || saturated(f.ay) || saturated(f.az) ||
      saturated(f.gx) || saturated(f.gy) || saturated(f.gz)) {
    f.status_flags |= SENSOR_STATUS_SATURATED; ++health.saturated;
  }
  latestFrame = f;
  sampleTimestampMs = millis();  // Same millisecond clock used by BLE SYNC_RESP.
}
bool pollSensor() {
  uint32_t previousSequence = sequence;
  if (Serial.available()) {
    int c = Serial.read();
    if (c == 'd') { printHealth(); printBleHealth(); }
    else if (c >= '1' && c <= '3') triggerHapticPattern(static_cast<HapticPattern>(c-'1'));
  }
  updateHapticPattern();
  if (nodeState == FAULT) recoverImu();
  uint32_t now = micros();
  if (nodeState == STREAMING && static_cast<int32_t>(now-nextSampleUs) >= 0)
    acquireAndProcess(now);
  return sequence != previousSequence;
}
