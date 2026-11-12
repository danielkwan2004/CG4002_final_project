#pragma once
#include "NodeConfig.h"

namespace HapticsConfig {
constexpr bool ENABLED = SOM_NODE_ROLE == SOM_FOREARM;
constexpr int PIN = 25;
constexpr uint8_t DUTY = 255;
constexpr uint16_t PULSE_MS = 150;
constexpr uint16_t DOUBLE_GAP_MS = 250;
constexpr uint16_t TRIPLE_GAP_MS = 100;
constexpr uint16_t PATTERN_GAP_MS = 100;
constexpr uint8_t QUEUE_SIZE = 4; // Waiting patterns, plus the active one.
}
