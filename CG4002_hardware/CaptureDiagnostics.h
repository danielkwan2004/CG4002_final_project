#ifndef CAPTURE_DIAGNOSTICS_H
#define CAPTURE_DIAGNOSTICS_H

#include "Calibration.h"
#include "ICM42686P.h"
#include "WiFiTelemetry.h"
#include "ImuHealth.h"

struct BurstCounters {
  uint32_t id = 0;
  uint32_t firstSeq = 0;
  uint32_t lastSeq = 0;
  unsigned long firstUs = 0;
  unsigned long lastUs = 0;
  uint32_t attempted = 0;
  uint32_t accepted = 0;
  uint32_t failed = 0;
  uint32_t pending = 0;
  bool gateClosed = false;
  bool dirty = true;
  bool interrupted = false;
};

// Diagnostics are cumulative per boot. Losing a heartbeat does not lose the
// timing counters. Data and diagnostics both use UDP; absent evidence is never
// proof of delivery. The last eight completed burst summaries are repeated.
class CaptureDiagnostics {
public:
  void begin(uint8_t node, uint32_t boot);
  unsigned long recordAcquisition(unsigned long timestampUs,
      unsigned long readUs, unsigned long latenessUs, uint32_t skipped);
  void recordIdle(const SensorFrame& frame, const GyroCalibration& bias);
  void startBurst(const SensorFrame& frame);
  uint32_t burstId() const { return current.id; }
  uint32_t burstIndex() const { return current.attempted; }
  void recordQueued(const SensorFrame& frame, bool admitted);
  void recordDelivery(uint32_t burst, uint32_t count, bool accepted);
  void endBurst(WiFiTelemetry& wifi, bool interrupted = false);
  void recordImuHealth(const ImuHealth& health) { imuHealth = health; }
  void recordMissedAcquisition(unsigned long readUs, unsigned long latenessUs,
                               uint32_t skipped);
  bool publishFinalBurst(WiFiTelemetry& wifi);
  void sendConfiguration(WiFiTelemetry& wifi, const ImuRegisterReadback& regs,
      const GyroCalibration& gyro, const AccelCalibration& accel,
      const char* state, float alpha, int calibrationSamples);
  bool requestHeartbeat(bool includeConfiguration);
  bool heartbeatPending() const { return heartbeatStage != HeartbeatStage::Idle; }
  // One packet at most, with >=10 ms between parts. Each part snapshots its
  // own current counters; produced values may differ across a heartbeat.
  bool serviceHeartbeat(WiFiTelemetry& wifi, uint32_t nowUs, const char* state,
      unsigned long dropped, int highWater, unsigned long processingUs,
      unsigned long wifiUs, const ImuRegisterReadback& regs,
      const GyroCalibration& gyro, const AccelCalibration& accel,
      float alpha, int calibrationSamples);
  void recordTelemetryCost(unsigned long durationUs, bool diagnostic);

private:
  enum class HeartbeatStage { Idle, Timing, ActiveBurst, History, Transport, Queue, Configuration };
  void sendTiming(WiFiTelemetry& wifi, const char* state,
      unsigned long dropped, int highWater, unsigned long processingUs,
      unsigned long wifiUs);
  bool sendBurst(WiFiTelemetry& wifi, const BurstCounters& burst);
  bool sendJson(WiFiTelemetry& wifi, const char* packet, int length, size_t capacity);
  uint8_t nodeId = 0;
  uint32_t bootId = 0;
  uint32_t produced = 0;
  ImuHealth imuHealth;
  uint32_t intervals = 0;
  unsigned long previousUs = 0;
  uint64_t intervalSumUs = 0;
  unsigned long minIntervalUs = 0xFFFFFFFFUL;
  unsigned long maxIntervalUs = 0;
  uint32_t histogram[6] = {};
  uint32_t skippedDeadlines = 0;
  unsigned long maxLatenessUs = 0;
  unsigned long maxReadUs = 0;
  unsigned long maxProcessingUs = 0;
  unsigned long maxWifiUs = 0;
  unsigned long maxDiagnosticUs = 0;
  uint32_t attempted = 0;
  uint32_t accepted = 0;
  uint32_t failed = 0;
  uint32_t pending = 0;
  uint32_t diagnosticFailures = 0;
  uint32_t burstCount = 0;
  uint32_t idleSamples = 0;
  double idleGyroSum[3] = {};
  double idleAccelSum[3] = {};
  BurstCounters current;
  static const uint8_t HISTORY_SIZE = 8;
  BurstCounters history[HISTORY_SIZE];
  uint8_t historyWrite = 0;
  uint8_t historyCount = 0;
  uint8_t historyReplay = 0;
  unsigned long lastFinalReportMs = 0;
  HeartbeatStage heartbeatStage = HeartbeatStage::Idle;
  bool heartbeatConfiguration = false, heartbeatSentPart = false;
  uint32_t lastHeartbeatPartUs = 0;
};

#endif
