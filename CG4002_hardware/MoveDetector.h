#ifndef MOVE_DETECTOR_H
#define MOVE_DETECTOR_H

#include <Arduino.h>

namespace MoveConfig {
constexpr float GYRO_START_THRESHOLD_DPS = 40.0f;
constexpr float GYRO_STOP_THRESHOLD_DPS = 15.0f;
constexpr float ACCEL_START_THRESHOLD_G = 0.3f;
constexpr float ACCEL_STOP_THRESHOLD_G = 0.15f;
constexpr unsigned long MOVE_MIN_QUIET_MS = 150;
}

enum MoveEvent : uint8_t {
  MOVE_EVENT_NONE = 0,
  MOVE_EVENT_STARTED,
  MOVE_EVENT_ENDED
};

// Placeholder start-of-move / end-of-move gate: a magnitude threshold with
// hysteresis and a debounce timer, not a real gesture classifier. Its only
// job is deciding *when* the node should stream data, not *what* the move
// is -- thresholds are rough bench-test guesses and need retuning against
// real recorded actions.
class MoveDetector {
public:
  MoveDetector();

  // gyroMagDps: sqrt(gx^2+gy^2+gz^2) of the filtered gyro reading, dps.
  // accelDeviationG: |accel magnitude - 1g| of the filtered accel reading.
  // nowMs: millis() at the time of this sample -- using wall time rather
  // than a sample count keeps the debounce window correct even if the
  // sample rate changes later.
  MoveEvent update(float gyroMagDps, float accelDeviationG, unsigned long nowMs);

  bool isActive() const;

private:
  bool active;
  bool belowStopThreshold;
  unsigned long belowStopSinceMs;
};

#endif
