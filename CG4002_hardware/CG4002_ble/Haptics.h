#pragma once
#include <Arduino.h>
enum HapticPattern {
  HAPTIC_SINGLE_PULSE,
  HAPTIC_DOUBLE_PULSE,
  HAPTIC_FAULT_PATTERN
};
void beginHaptics();
void triggerHapticPattern(HapticPattern pattern);
void updateHapticPattern();
