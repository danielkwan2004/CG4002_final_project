#include "MoveDetector.h"

// Placeholder thresholds only -- not yet calibrated against real actions.
namespace {
const float GYRO_START_THRESHOLD_DPS = 40.0f;
const float GYRO_STOP_THRESHOLD_DPS = 15.0f;
const float ACCEL_START_THRESHOLD_G = 0.3f;
const float ACCEL_STOP_THRESHOLD_G = 0.15f;
const unsigned long MOVE_MIN_QUIET_MS = 150;
}  // namespace

MoveDetector::MoveDetector()
    : active(false), belowStopThreshold(false), belowStopSinceMs(0) {}

MoveEvent MoveDetector::update(float gyroMagDps, float accelDeviationG, unsigned long nowMs) {
  bool aboveStartThreshold =
      gyroMagDps >= GYRO_START_THRESHOLD_DPS || accelDeviationG >= ACCEL_START_THRESHOLD_G;
  bool belowStopThresholdNow =
      gyroMagDps < GYRO_STOP_THRESHOLD_DPS && accelDeviationG < ACCEL_STOP_THRESHOLD_G;

  if (!active) {
    if (aboveStartThreshold) {
      active = true;
      belowStopThreshold = false;
      return MOVE_EVENT_STARTED;
    }
    return MOVE_EVENT_NONE;
  }

  if (!belowStopThresholdNow) {
    belowStopThreshold = false;
    return MOVE_EVENT_NONE;
  }

  if (!belowStopThreshold) {
    belowStopThreshold = true;
    belowStopSinceMs = nowMs;
    return MOVE_EVENT_NONE;
  }

  if (nowMs - belowStopSinceMs >= MOVE_MIN_QUIET_MS) {
    active = false;
    belowStopThreshold = false;
    return MOVE_EVENT_ENDED;
  }

  return MOVE_EVENT_NONE;
}

bool MoveDetector::isActive() const {
  return active;
}
