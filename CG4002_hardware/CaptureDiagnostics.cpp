#include "CaptureDiagnostics.h"
#include "MoveDetector.h"
#include "TelemetryScheduler.h"

void CaptureDiagnostics::begin(uint8_t node, uint32_t boot) {
  nodeId = node;
  bootId = boot;
}

unsigned long CaptureDiagnostics::recordAcquisition(unsigned long timestampUs,
    unsigned long readUs, unsigned long latenessUs, uint32_t skipped) {
  unsigned long interval = 0;
  if (produced != 0) {
    interval = timestampUs - previousUs;  // unsigned subtraction survives micros wrap
    ++intervals;
    intervalSumUs += interval;
    if (interval < minIntervalUs) minIntervalUs = interval;
    if (interval > maxIntervalUs) maxIntervalUs = interval;
    uint8_t bin = interval < 4000 ? 0 : interval < 4500 ? 1 :
                  interval < 5500 ? 2 : interval < 6000 ? 3 :
                  interval < 10000 ? 4 : 5;
    ++histogram[bin];
  }
  ++produced;
  previousUs = timestampUs;
  skippedDeadlines += skipped;
  if (latenessUs > maxLatenessUs) maxLatenessUs = latenessUs;
  if (readUs > maxReadUs) maxReadUs = readUs;
  return interval;
}

void CaptureDiagnostics::recordIdle(const SensorFrame& frame, const GyroCalibration& bias) {
  ++idleSamples;
  // Gate-idle is not a stationary detector. The operator supplies a stationary
  // test pose; these cumulative sums let a receiver compare quiet windows.
  idleGyroSum[0] += (frame.gx - bias.biasX) / ImuConfig::GYRO_LSB_PER_DPS;
  idleGyroSum[1] += (frame.gy - bias.biasY) / ImuConfig::GYRO_LSB_PER_DPS;
  idleGyroSum[2] += (frame.gz - bias.biasZ) / ImuConfig::GYRO_LSB_PER_DPS;
  idleAccelSum[0] += frame.ax_g;
  idleAccelSum[1] += frame.ay_g;
  idleAccelSum[2] += frame.az_g;
}

void CaptureDiagnostics::recordMissedAcquisition(unsigned long readUs,
    unsigned long latenessUs, uint32_t skipped) {
  skippedDeadlines += skipped;
  if (readUs > maxReadUs) maxReadUs = readUs;
  if (latenessUs > maxLatenessUs) maxLatenessUs = latenessUs;
}

void CaptureDiagnostics::startBurst(const SensorFrame& frame) {
  current = BurstCounters();
  current.id = ++burstCount;
  current.firstSeq = frame.seq;
  current.lastSeq = frame.seq;
  current.firstUs = frame.timestamp_us;
  current.lastUs = frame.timestamp_us;
}

void CaptureDiagnostics::recordQueued(const SensorFrame& frame, bool admitted) {
  current.lastSeq = frame.seq;
  current.lastUs = frame.timestamp_us;
  ++current.attempted;
  ++attempted;
  if (admitted) {
    ++current.pending;
    ++pending;
  } else {
    ++current.failed;
    ++failed;
  }
}

void CaptureDiagnostics::recordDelivery(uint32_t burst, uint32_t n, bool sent) {
  BurstCounters* target = current.id == burst ? &current : nullptr;
  for (uint8_t i = 0; !target && i < historyCount; ++i)
    if (history[i].id == burst) target = &history[i];
  // Every queued sample has a retained burst, including history-eviction drops.
  if (!target || target->pending < n) return;
  target->pending -= n;
  pending -= n;
  if (sent) { target->accepted += n; accepted += n; }
  else { target->failed += n; failed += n; }
  target->dirty = true;
}

bool CaptureDiagnostics::sendJson(WiFiTelemetry& wifi, const char* packet,
                                  int length, size_t capacity) {
  if (length <= 0 || static_cast<size_t>(length) >= capacity ||
      !wifi.sendPacket(packet, static_cast<size_t>(length))) {
    ++diagnosticFailures;
    return false;
  }
  return true;
}

bool CaptureDiagnostics::sendBurst(WiFiTelemetry& wifi, const BurstCounters& burst) {
  char packet[384];
  int length = snprintf(packet, sizeof(packet),
      "{\"v\":4,\"type\":\"burst\",\"node\":%u,\"boot\":%lu,\"id\":%lu,"
      "\"closed\":%s,\"gate_closed\":%s,\"pending\":%lu,\"first_seq\":%lu,\"last_seq\":%lu,\"first_us\":%lu,"
      "\"last_us\":%lu,\"attempted\":%lu,\"accepted\":%lu,\"failed\":%lu,\"interrupted\":%s}",
      nodeId, (unsigned long)bootId, (unsigned long)burst.id,
      burst.gateClosed && burst.pending == 0 ? "true" : "false",
      burst.gateClosed ? "true" : "false", (unsigned long)burst.pending,
      (unsigned long)burst.firstSeq,
      (unsigned long)burst.lastSeq, burst.firstUs, burst.lastUs,
      (unsigned long)burst.attempted, (unsigned long)burst.accepted,
      (unsigned long)burst.failed, burst.interrupted ? "true" : "false");
  return sendJson(wifi, packet, length, sizeof(packet));
}

void CaptureDiagnostics::endBurst(WiFiTelemetry& wifi, bool interrupted) {
  if (!current.id) return;
  current.interrupted = interrupted;
  current.gateClosed = true;
  wifi.closeBurst(current.id);
  if (history[historyWrite].pending)
    wifi.cancelThrough(history[historyWrite].id, *this);
  history[historyWrite] = current;
  historyWrite = (historyWrite + 1) % HISTORY_SIZE;
  if (historyCount < HISTORY_SIZE) ++historyCount;
  current = BurstCounters();  // pending outcomes now update the retained history
}

bool CaptureDiagnostics::publishFinalBurst(WiFiTelemetry& wifi) {
  // Publish settled counts promptly even if many short bursts finish between
  // one-second heartbeats. A failed control send stays dirty for a later try.
  // One attempt at most, spaced out; this never runs a blocking retry loop.
  if (millis() - lastFinalReportMs < 10) return false;
  for (uint8_t i = 0; i < historyCount; ++i) {
    uint8_t slot = (historyReplay + i) % historyCount;
    BurstCounters& b = history[slot];
    if (b.dirty && b.gateClosed && b.pending == 0) {
      lastFinalReportMs = millis();
      if (sendBurst(wifi, b)) b.dirty = false;
      historyReplay = (slot + 1) % historyCount;
      return true;
    }
  }
  return false;
}

void CaptureDiagnostics::sendConfiguration(WiFiTelemetry& wifi,
    const ImuRegisterReadback& regs, const GyroCalibration& gyro,
    const AccelCalibration& accel, const char* state, float alpha,
    int calibrationSamples) {
  char packet[896];
  int length = snprintf(packet, sizeof(packet),
      "{\"v\":4,\"type\":\"config\",\"node\":%u,\"boot\":%lu,\"produced\":%lu,"
      "\"state\":\"%s\",\"verified\":%s,\"who\":%u,\"gyro_config\":%u,"
      "\"accel_config\":%u,\"pwr_mgmt\":%u,\"gyro_fs_dps\":2000,\"accel_fs_g\":16,"
      "\"gyro_lsb_per_dps\":%.1f,\"accel_lsb_per_g\":%.1f,\"period_us\":%lu,"
      "\"diag_scheduler\":\"staggered_v1\",\"telemetry_headroom_us\":%lu,"
      "\"calibration_samples\":%d,\"gyro_bias_counts\":[%.6f,%.6f,%.6f],"
      "\"accel_offset_g\":[%.6f,%.6f,%.6f],\"alpha\":%.3f,"
      "\"gyro_start_dps\":%.1f,\"gyro_stop_dps\":%.1f,"
      "\"accel_start_g\":%.2f,\"accel_stop_g\":%.2f,\"quiet_ms\":%lu}",
      nodeId, (unsigned long)bootId, (unsigned long)produced, state,
      regs.verified ? "true" : "false", regs.whoAmI, regs.gyroConfig0,
      regs.accelConfig0, regs.pwrMgmt0, ImuConfig::GYRO_LSB_PER_DPS,
      ImuConfig::ACCEL_LSB_PER_G, ImuConfig::SAMPLE_PERIOD_US,
      (unsigned long)TelemetryScheduler::HEADROOM_US, calibrationSamples,
      gyro.biasX, gyro.biasY, gyro.biasZ,
      accel.offsetX_g, accel.offsetY_g, accel.offsetZ_g, alpha,
      MoveConfig::GYRO_START_THRESHOLD_DPS, MoveConfig::GYRO_STOP_THRESHOLD_DPS,
      MoveConfig::ACCEL_START_THRESHOLD_G, MoveConfig::ACCEL_STOP_THRESHOLD_G,
      MoveConfig::MOVE_MIN_QUIET_MS);
  sendJson(wifi, packet, length, sizeof(packet));
}

void CaptureDiagnostics::recordTelemetryCost(unsigned long durationUs, bool diagnostic) {
  if (durationUs > maxWifiUs) maxWifiUs = durationUs;
  if (diagnostic && durationUs > maxDiagnosticUs) maxDiagnosticUs = durationUs;
}

bool CaptureDiagnostics::requestHeartbeat(bool includeConfiguration) {
  if (heartbeatPending()) return false;  // coalesce, never restart unfinished work
  heartbeatStage = HeartbeatStage::Timing;
  heartbeatConfiguration = includeConfiguration;
  heartbeatSentPart = false;
  return true;
}

bool CaptureDiagnostics::serviceHeartbeat(WiFiTelemetry& wifi, uint32_t nowUs,
    const char* state, unsigned long dropped, int highWater,
    unsigned long processingUs, unsigned long wifiUs,
    const ImuRegisterReadback& regs, const GyroCalibration& gyro,
    const AccelCalibration& accel, float alpha, int calibrationSamples) {
  if (!heartbeatPending() || (heartbeatSentPart &&
      static_cast<uint32_t>(nowUs - lastHeartbeatPartUs) < 10000)) return false;
  // Skip absent burst parts, never loop over sends. Return immediately after
  // ONE packet attempt, even on failure; ordinary diagnostics repeat next cycle.
  while (heartbeatPending()) {
    const HeartbeatStage part = heartbeatStage;
    heartbeatStage = static_cast<HeartbeatStage>(static_cast<int>(part) + 1);
    switch (part) {
      case HeartbeatStage::Timing:
        sendTiming(wifi, state, dropped, highWater, processingUs, wifiUs);
        break;
      case HeartbeatStage::ActiveBurst:
        if (!current.id) continue;
        sendBurst(wifi, current);
        break;
      case HeartbeatStage::History: {
        if (!historyCount) continue;
        historyReplay %= historyCount;
        for (uint8_t i = 0; i < historyCount; ++i) {
          uint8_t candidate = (historyReplay + i) % historyCount;
          if (history[candidate].dirty) { historyReplay = candidate; break; }
        }
        if (sendBurst(wifi, history[historyReplay])) history[historyReplay].dirty = false;
        historyReplay = (historyReplay + 1) % historyCount;
        break;
      }
      case HeartbeatStage::Transport: {
        char packet[1400];
        int length = wifi.formatDiagnostics(packet, sizeof(packet), nodeId, bootId, produced);
        sendJson(wifi, packet, length, sizeof(packet));
        break;
      }
      case HeartbeatStage::Queue: {
        char packet[1400];
        int length = wifi.formatQueueDiagnostics(packet, sizeof(packet), nodeId, bootId, produced);
        sendJson(wifi, packet, length, sizeof(packet));
        if (!heartbeatConfiguration) heartbeatStage = HeartbeatStage::Idle;
        break;
      }
      case HeartbeatStage::Configuration:
        heartbeatStage = HeartbeatStage::Idle;
        sendConfiguration(wifi, regs, gyro, accel, state, alpha, calibrationSamples);
        break;
      case HeartbeatStage::Idle:
        return false;
    }
    lastHeartbeatPartUs = nowUs;
    heartbeatSentPart = true;
    return true;
  }
  return false;
}

void CaptureDiagnostics::sendTiming(WiFiTelemetry& wifi, const char* state,
    unsigned long dropped, int highWater, unsigned long processingUs,
    unsigned long wifiUs) {
  if (processingUs > maxProcessingUs) maxProcessingUs = processingUs;
  if (wifiUs > maxWifiUs) maxWifiUs = wifiUs;
  char packet[1400];
  int length = snprintf(packet, sizeof(packet),
      "{\"v\":4,\"type\":\"timing\",\"node\":%u,\"boot\":%lu,\"state\":\"%s\","
      "\"produced\":%lu,\"intervals\":%lu,\"sum_dt_us\":%llu,\"min_dt_us\":%lu,"
      "\"max_dt_us\":%lu,\"hist\":[%lu,%lu,%lu,%lu,%lu,%lu],"
      "\"skipped_deadlines\":%lu,\"max_late_us\":%lu,\"max_read_us\":%lu,"
      "\"max_processing_us\":%lu,\"max_wifi_us\":%lu,\"max_diag_us\":%lu,\"dropped\":%lu,\"high_water\":%d,"
      "\"attempted\":%lu,\"accepted\":%lu,\"failed\":%lu,\"pending\":%lu,\"diag_failed\":%lu,"
      "\"bursts_started\":%lu,\"active_burst\":%lu,\"idle_samples\":%lu,"
      "\"imu_read_failures\":%lu,\"imu_consecutive\":%lu,\"imu_max_consecutive\":%lu,"
      "\"imu_recovery_attempts\":%lu,\"imu_recoveries\":%lu,\"saturated_samples\":%lu,"
      "\"idle_gyro_sum\":[%.6f,%.6f,%.6f],\"idle_accel_sum\":[%.6f,%.6f,%.6f]}",
      nodeId, (unsigned long)bootId, state, (unsigned long)produced,
      (unsigned long)intervals, (unsigned long long)intervalSumUs,
      intervals ? minIntervalUs : 0UL, maxIntervalUs,
      (unsigned long)histogram[0], (unsigned long)histogram[1],
      (unsigned long)histogram[2], (unsigned long)histogram[3],
      (unsigned long)histogram[4], (unsigned long)histogram[5],
      (unsigned long)skippedDeadlines, maxLatenessUs, maxReadUs,
      maxProcessingUs, maxWifiUs, maxDiagnosticUs, dropped, highWater, (unsigned long)attempted,
      (unsigned long)accepted, (unsigned long)failed, (unsigned long)pending,
      (unsigned long)diagnosticFailures,
      (unsigned long)burstCount, (unsigned long)current.id,
      (unsigned long)idleSamples,
      (unsigned long)imuHealth.readFailures, (unsigned long)imuHealth.consecutive,
      (unsigned long)imuHealth.maxConsecutive, (unsigned long)imuHealth.recoveryAttempts,
      (unsigned long)imuHealth.recoveries, (unsigned long)imuHealth.saturated,
      idleGyroSum[0], idleGyroSum[1], idleGyroSum[2],
      idleAccelSum[0], idleAccelSum[1], idleAccelSum[2]);
  sendJson(wifi, packet, length, sizeof(packet));
}
