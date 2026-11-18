#include "Haptics.h"
#include "HapticsConfig.h"
#include <cstring>
const int HAPTIC_PIN = HapticsConfig::PIN;
const int HAPTIC_DUTY_ON = HapticsConfig::DUTY;


const char* hapticPatternName(HapticPattern pattern) {
  switch (pattern) {
    case HAPTIC_SINGLE_PULSE: return "SINGLE_PULSE";
    case HAPTIC_DOUBLE_PULSE: return "DOUBLE_PULSE";
    case HAPTIC_FAULT_PATTERN: return "TRIPLE_PULSE";
    default: return "UNKNOWN";
  }
}

// Non-blocking PWM waveform player: each pattern is a sequence of
// (duty, duration) steps, advanced from loop() via updateHapticPattern()
// without delay(). Other loop work can still extend the step durations.
struct HapticStep {
  uint8_t duty;
  uint16_t durationMs;
};

const HapticStep HAPTIC_STEPS_SINGLE_PULSE[] = {
  { HAPTIC_DUTY_ON, HapticsConfig::PULSE_MS },
};

const HapticStep HAPTIC_STEPS_DOUBLE_PULSE[] = {
  { HAPTIC_DUTY_ON, HapticsConfig::PULSE_MS },
  { 0, HapticsConfig::DOUBLE_GAP_MS },
  { HAPTIC_DUTY_ON, HapticsConfig::PULSE_MS },
};

// ERM motors need time to spin up, so short (~80ms) pulses barely register --
// each on-step here is as long as the single pulse to give it full strength.
const HapticStep HAPTIC_STEPS_FAULT_PATTERN[] = {
  { HAPTIC_DUTY_ON, HapticsConfig::PULSE_MS },
  { 0, HapticsConfig::TRIPLE_GAP_MS },
  { HAPTIC_DUTY_ON, HapticsConfig::PULSE_MS },
  { 0, HapticsConfig::TRIPLE_GAP_MS },
  { HAPTIC_DUTY_ON, HapticsConfig::PULSE_MS },
};

const HapticStep* hapticActiveSteps = nullptr;
uint8_t hapticStepCount = 0;
uint8_t hapticStepIndex = 0;
uint32_t hapticStepStartMs = 0;
bool hapticPatternRunning = false;
HapticPattern hapticQueue[HapticsConfig::QUEUE_SIZE];
uint8_t hapticQueueHead = 0, hapticQueueCount = 0;
uint32_t hapticReadyMs = 0;

bool parseHapticPattern(const char* name, HapticPattern& pattern) {
  if (!name) return false;
  if (std::strcmp(name, "single") == 0) pattern = HAPTIC_SINGLE_PULSE;
  else if (std::strcmp(name, "double") == 0) pattern = HAPTIC_DOUBLE_PULSE;
  else if (std::strcmp(name, "triple") == 0) pattern = HAPTIC_TRIPLE_PULSE;
  else return false;
  return true;
}
bool hapticsBusy() { return hapticPatternRunning; }
uint8_t pendingHapticPatterns() { return hapticQueueCount; }
void stopHaptics() {
  analogWrite(HAPTIC_PIN, 0);
  hapticPatternRunning = false;
  hapticQueueHead = hapticQueueCount = 0;
  hapticReadyMs = millis();
}
bool enqueueHapticPattern(HapticPattern pattern) {
  if (!HapticsConfig::ENABLED || pattern < HAPTIC_SINGLE_PULSE || pattern > HAPTIC_TRIPLE_PULSE)
    return false;
  if (!hapticPatternRunning && !hapticQueueCount && int32_t(uint32_t(millis())-hapticReadyMs) >= 0) { triggerHapticPattern(pattern); return true; }
  if (hapticQueueCount == HapticsConfig::QUEUE_SIZE) return false;
  hapticQueue[(hapticQueueHead + hapticQueueCount) % HapticsConfig::QUEUE_SIZE] = pattern;
  ++hapticQueueCount;
  return true;
}

void triggerHapticPattern(HapticPattern pattern) {
  if (!HapticsConfig::ENABLED) return;
  switch (pattern) {
    case HAPTIC_SINGLE_PULSE:
      hapticActiveSteps = HAPTIC_STEPS_SINGLE_PULSE;
      hapticStepCount = sizeof(HAPTIC_STEPS_SINGLE_PULSE) / sizeof(HapticStep);
      break;
    case HAPTIC_DOUBLE_PULSE:
      hapticActiveSteps = HAPTIC_STEPS_DOUBLE_PULSE;
      hapticStepCount = sizeof(HAPTIC_STEPS_DOUBLE_PULSE) / sizeof(HapticStep);
      break;
    case HAPTIC_FAULT_PATTERN:
    default:
      hapticActiveSteps = HAPTIC_STEPS_FAULT_PATTERN;
      hapticStepCount = sizeof(HAPTIC_STEPS_FAULT_PATTERN) / sizeof(HapticStep);
      break;
  }

  hapticStepIndex = 0;
  hapticStepStartMs = millis();
  hapticPatternRunning = true;
  analogWrite(HAPTIC_PIN, hapticActiveSteps[0].duty);

  Serial.print("[haptic] pattern=");
  Serial.println(hapticPatternName(pattern));
}

void updateHapticPattern() {
  if (!hapticPatternRunning) {
    if (hapticQueueCount && int32_t(uint32_t(millis())-hapticReadyMs) >= 0) {
      auto pattern = hapticQueue[hapticQueueHead];
      hapticQueueHead = (hapticQueueHead + 1) % HapticsConfig::QUEUE_SIZE;
      --hapticQueueCount;
      triggerHapticPattern(pattern);
    }
    return;
  }

  uint32_t elapsedMs = uint32_t(millis()) - hapticStepStartMs;
  if (elapsedMs < hapticActiveSteps[hapticStepIndex].durationMs) {
    return;
  }

  hapticStepIndex++;
  if (hapticStepIndex >= hapticStepCount) {
    analogWrite(HAPTIC_PIN, 0);
    hapticPatternRunning = false;
    hapticReadyMs = uint32_t(millis()) + HapticsConfig::PATTERN_GAP_MS;
    return;
  }

  hapticStepStartMs = millis();
  analogWrite(HAPTIC_PIN, hapticActiveSteps[hapticStepIndex].duty);
}


void beginHaptics() { pinMode(HAPTIC_PIN, OUTPUT); stopHaptics(); }
