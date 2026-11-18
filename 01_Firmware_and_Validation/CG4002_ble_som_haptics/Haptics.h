#pragma once
#include <Arduino.h>
enum HapticPattern {
  HAPTIC_SINGLE_PULSE,
  HAPTIC_DOUBLE_PULSE,
  HAPTIC_FAULT_PATTERN,
  HAPTIC_TRIPLE_PULSE = HAPTIC_FAULT_PATTERN
};
void beginHaptics();
void triggerHapticPattern(HapticPattern pattern);
void updateHapticPattern();
bool parseHapticPattern(const char* name, HapticPattern& pattern);
bool enqueueHapticPattern(HapticPattern pattern);
void stopHaptics();
bool hapticsBusy();
uint8_t pendingHapticPatterns();
