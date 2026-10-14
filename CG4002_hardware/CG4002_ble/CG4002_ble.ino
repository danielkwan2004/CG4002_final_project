#include "ICM42686P.h"
#include "Calibration.h"
#include "AxisMapping.h"
#include "LowPassFilter.h"
#include "MoveDetector.h"
#include "ImuHealth.h"
#include "Haptics.h"
#include "BleTelemetry.h"
#include <esp_system.h>

// Independent spin-off of the working Wi-Fi checkpoint. No network credentials,
// UDP diagnostics, simulated telemetry or synchronization handshake required.
constexpr uint8_t NODE_ID = 1;
constexpr const char* BLE_NAME = "CG4002-Forearm";
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
BleTelemetry telemetry;
ImuHealth health;
GyroCalibration gyroCalibration = {};
AccelCalibration accelCalibration = {};
LowPassFilter filters[6];
MoveDetector movement;
bool readFailed = false, calibrationFailed = false, recoverable = false;
uint32_t bootId = 0, sequence = 0, burst = 0, nextSampleUs = 0;
uint32_t lastRecoveryMs = 0, lastErrorLogMs = 0, lastStatusMs = 0;
uint32_t previousReadUs = 0, skippedSlots = 0, minDtUs = UINT32_MAX, maxDtUs = 0;
uint32_t maxReadUs = 0, maxServiceUs = 0;
uint64_t intervalSumUs = 0;

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
  movement = MoveDetector();
  setState(FAULT);
}
void printHealth() {
  const auto& e = imu.lastError();
  const auto& q = telemetry.counters();
  const auto link = telemetry.link();
  Serial.printf("[health] state=%s seq=%lu active=%u failures=%lu consecutive=%lu recoveries=%lu saturated=%lu stage=%s reg=0x%02X wire=%u bytes=%u/%u\n",
      stateName(), (unsigned long)sequence, movement.isActive(),
      (unsigned long)health.readFailures, (unsigned long)health.consecutive,
      (unsigned long)health.recoveries, (unsigned long)health.saturated,
      e.stage, e.reg, e.wireStatus, (unsigned)e.received, (unsigned)e.expected);
  Serial.printf("[ble] subscribed=%u mtu=%u offered=%lu accepted=%lu dropped=%lu pending=%u retries=%lu offline_samples=%lu\n",
      link.subscribed, link.mtu, (unsigned long)q.offered, (unsigned long)q.accepted,
      (unsigned long)q.dropped, (unsigned)q.pending(), (unsigned long)q.retries,
      (unsigned long)telemetry.offlineSamples());
  Serial.printf("[timing] skipped=%lu max_read_us=%lu max_ble_service_us=%lu\n",
      (unsigned long)skippedSlots, (unsigned long)maxReadUs, (unsigned long)maxServiceUs);
}
SensorFrame readSensor() {
  SensorFrame f = {};
  readFailed = !imu.readRaw(f);
  if (readFailed) {
    if (nodeState == CALIBRATING) calibrationFailed = true;
  } else applyAxisMapping(f, NODE_AXIS_MAPPING);
  return f;
}
void publishStatus() {
  const auto link = telemetry.link();
  const auto& q = telemetry.counters();
  char status[512];
  double hz = intervalSumUs ? (sequence-1) * 1000000.0 / intervalSumUs : 0;
  int n = snprintf(status, sizeof(status),
      "{\"v\":1,\"node\":%u,\"boot\":%lu,\"session\":%lu,\"state\":\"%s\",\"reason\":\"%s\","
      "\"active\":%s,\"burst\":%lu,\"produced\":%lu,\"hz\":%.3f,\"min_dt\":%lu,\"max_dt\":%lu,"
      "\"skipped\":%lu,\"read_failures\":%lu,\"recoveries\":%lu,\"saturated\":%lu,"
      "\"mtu\":%u,\"subscribed\":%s,\"offered\":%lu,\"accepted\":%lu,\"dropped\":%lu,"
      "\"pending\":%u,\"retries\":%lu,\"offline\":%lu,\"verified\":%s}",
      NODE_ID, (unsigned long)bootId, (unsigned long)link.session, stateName(), faultReason,
      movement.isActive() ? "true" : "false", (unsigned long)burst, (unsigned long)sequence, hz,
      (unsigned long)(sequence > 1 ? minDtUs : 0), (unsigned long)maxDtUs,
      (unsigned long)skippedSlots, (unsigned long)health.readFailures,
      (unsigned long)health.recoveries, (unsigned long)health.saturated,
      link.mtu, link.subscribed ? "true" : "false", (unsigned long)q.offered,
      (unsigned long)q.accepted, (unsigned long)q.dropped, (unsigned)q.pending(),
      (unsigned long)q.retries, (unsigned long)telemetry.offlineSamples(),
      imu.configuration().verified ? "true" : "false");
  if (n > 0 && n < static_cast<int>(sizeof(status))) telemetry.setStatus(status);
}
void setup() {
  Serial.begin(115200);
  delay(1000);
  beginHaptics();
  bootId = esp_random();
  if (!telemetry.begin(BLE_NAME, NODE_ID, bootId)) {
    enterFault("ble_startup", false); return;
  }
  if (!Wire.begin(SDA_PIN, SCL_PIN, 400000)) {
    enterFault("i2c_startup", false); return;
  }
  Wire.setTimeOut(I2C_TIMEOUT_MS);
  if (!imu.begin(Wire)) {
    enterFault("imu_startup", false); printHealth(); return;
  }
  setState(CALIBRATING);
  publishStatus();
  Serial.println("Keep flat with +Z upward and still through BOTH calibrations (~4 s).");
  gyroCalibration = calibrateGyroscope(readSensor, CALIBRATION_SAMPLES, 5);
  accelCalibration = calibrateAccelerometer(readSensor, CALIBRATION_SAMPLES, 5);
  if (calibrationFailed) {
    enterFault("calibration_read_failed", false); printHealth(); return;
  }
  setState(STREAMING);
  Serial.printf("[calibration] gyro bias counts=(%.6f,%.6f,%.6f)\n",
      gyroCalibration.biasX, gyroCalibration.biasY, gyroCalibration.biasZ);
  Serial.println("[serial] d=health; 1/2/3=haptic patterns");
  nextSampleUs = micros();
  publishStatus();
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
    movement.interruptQuietWindow();
    bool sustained = health.failed();
    if (health.readFailures == 1 || millis()-lastErrorLogMs >= 1000 || sustained) {
      lastErrorLogMs = millis(); printHealth();
    }
    if (sustained) enterFault("imu_read_outage", true);
    return;
  }
  health.succeeded();
  f.node_id = NODE_ID; f.seq = sequence++;
  f.interval_us = f.seq ? static_cast<uint32_t>(f.timestamp_us-previousReadUs) : 0;
  previousReadUs = f.timestamp_us;
  if (f.seq) {
    intervalSumUs += f.interval_us;
    if (f.interval_us < minDtUs) minDtUs = f.interval_us;
    if (f.interval_us > maxDtUs) maxDtUs = f.interval_us;
  }
  f.ax_g -= accelCalibration.offsetX_g;
  f.ay_g -= accelCalibration.offsetY_g;
  f.az_g -= accelCalibration.offsetZ_g;
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
  float gyro = sqrtf(f.gx_filtered_dps*f.gx_filtered_dps +
      f.gy_filtered_dps*f.gy_filtered_dps + f.gz_filtered_dps*f.gz_filtered_dps);
  float accel = fabsf(sqrtf(f.ax_filtered_g*f.ax_filtered_g +
      f.ay_filtered_g*f.ay_filtered_g + f.az_filtered_g*f.az_filtered_g)-1.0f);
  bool wasActive = movement.isActive();
  MoveEvent event = movement.update(gyro, accel, millis());
  if (event == MOVE_EVENT_STARTED) ++burst;
  if (wasActive || movement.isActive()) {
    f.status_flags |= SENSOR_STATUS_MOVE_ACTIVE;
    telemetry.enqueue(f, burst, event == MOVE_EVENT_STARTED ? 1 : event == MOVE_EVENT_ENDED ? 2 : 0);
  }
}
void loop() {
  if (Serial.available()) {
    int c = Serial.read();
    if (c == 'd') printHealth();
    else if (c >= '1' && c <= '3') triggerHapticPattern(static_cast<HapticPattern>(c-'1'));
  }
  updateHapticPattern();
  if (nodeState == FAULT) recoverImu();
  uint32_t now = micros();
  if (nodeState == STREAMING && static_cast<int32_t>(now-nextSampleUs) >= 0)
    acquireAndProcess(now);
  // At most one BLE service slot per acquisition; keep time for the next read.
  static uint32_t servicedSequence = UINT32_MAX, lastFaultServiceUs = 0;
  now = micros();
  if (nodeState == STREAMING) {
    if (sequence == servicedSequence || static_cast<int32_t>(nextSampleUs-now) <= 3500) return;
    servicedSequence = sequence;
  } else {
    if (static_cast<uint32_t>(now-lastFaultServiceUs) < PERIOD_US) return;
    lastFaultServiceUs = now;
  }
  telemetry.service();
  if (millis()-lastStatusMs >= 1000) { lastStatusMs = millis(); publishStatus(); }
  uint32_t cost = micros()-now;
  if (cost > maxServiceUs) maxServiceUs = cost;
}
