#include "Haptics.h"
const int HAPTIC_PIN = 25;
const int HAPTIC_DUTY_ON = 255;


const char* hapticPatternName(HapticPattern pattern) {
  switch (pattern) {
    case HAPTIC_SINGLE_PULSE: return "SINGLE_PULSE";
    case HAPTIC_DOUBLE_PULSE: return "DOUBLE_PULSE";
    case HAPTIC_FAULT_PATTERN: return "FAULT_PATTERN";
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
  { HAPTIC_DUTY_ON, 150 },
};

const HapticStep HAPTIC_STEPS_DOUBLE_PULSE[] = {
  { HAPTIC_DUTY_ON, 150 },
  { 0, 250 },
  { HAPTIC_DUTY_ON, 150 },
};

// ERM motors need time to spin up, so short (~80ms) pulses barely register --
// each on-step here is as long as the single pulse to give it full strength.
const HapticStep HAPTIC_STEPS_FAULT_PATTERN[] = {
  { HAPTIC_DUTY_ON, 150 },
  { 0, 100 },
  { HAPTIC_DUTY_ON, 150 },
  { 0, 100 },
  { HAPTIC_DUTY_ON, 150 },
};

const HapticStep* hapticActiveSteps = nullptr;
uint8_t hapticStepCount = 0;
uint8_t hapticStepIndex = 0;
unsigned long hapticStepStartMs = 0;
bool hapticPatternRunning = false;

void triggerHapticPattern(HapticPattern pattern) {
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
    return;
  }

  unsigned long elapsedMs = millis() - hapticStepStartMs;
  if (elapsedMs < hapticActiveSteps[hapticStepIndex].durationMs) {
    return;
  }

  hapticStepIndex++;
  if (hapticStepIndex >= hapticStepCount) {
    analogWrite(HAPTIC_PIN, 0);
    hapticPatternRunning = false;
    return;
  }

  hapticStepStartMs = millis();
  analogWrite(HAPTIC_PIN, hapticActiveSteps[hapticStepIndex].duty);
}


void beginHaptics() { pinMode(HAPTIC_PIN, OUTPUT); analogWrite(HAPTIC_PIN, 0); }
