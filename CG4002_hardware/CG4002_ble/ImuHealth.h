#ifndef IMU_HEALTH_H
#define IMU_HEALTH_H

#include <stdint.h>

// A failed transaction is a missing sample, never a zero-valued sample.
// Retry at the next scheduled acquisition; only a sustained outage faults.
struct ImuHealth {
  static constexpr uint32_t FAILURE_LIMIT = 20;
  static constexpr uint32_t RECOVERY_INTERVAL_MS = 1000;
  uint32_t readFailures = 0;
  uint32_t consecutive = 0;
  uint32_t maxConsecutive = 0;
  uint32_t recoveryAttempts = 0;
  uint32_t recoveries = 0;
  uint32_t saturated = 0;

  bool failed() {
    ++readFailures;
    ++consecutive;
    if (consecutive > maxConsecutive) maxConsecutive = consecutive;
    return consecutive >= FAILURE_LIMIT;
  }
  void succeeded() { consecutive = 0; }
};

#endif
