#ifndef TELEMETRY_SCHEDULER_H
#define TELEMETRY_SCHEDULER_H

#include <stdint.h>

// A cooperative scheduling guard, not a hard real-time guarantee. Admit at
// most one potentially expensive network operation per completed acquisition,
// early enough to leave margin beyond the measured ~2.5 ms service cost.
class TelemetryScheduler {
public:
  static constexpr uint32_t HEADROOM_US = 3500;
  static constexpr uint32_t FAULT_SLOT_US = 5000;

  bool takeSlot(uint32_t now, uint32_t nextAcquisition, uint32_t produced,
                bool sampling) {
    if (sampling) {
      if (!produced || static_cast<int32_t>(nextAcquisition - now) <=
              static_cast<int32_t>(HEADROOM_US) ||
          (hasSampleSlot && lastProduced == produced)) return false;
      hasSampleSlot = true;
      lastProduced = produced;
    } else {
      // FAULT has no new acquisitions, but must still report and drain/expire.
      if (hasFaultSlot && static_cast<uint32_t>(now - lastFaultUs) < FAULT_SLOT_US)
        return false;
      hasFaultSlot = true;
      lastFaultUs = now;
    }
    return true;
  }

private:
  bool hasSampleSlot = false, hasFaultSlot = false;
  uint32_t lastProduced = 0, lastFaultUs = 0;
};

#endif
