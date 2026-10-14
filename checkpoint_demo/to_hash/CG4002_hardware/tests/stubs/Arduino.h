#pragma once
// Host-test declarations only. Firmware always uses the installed Arduino core.
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
using portMUX_TYPE = int;
#define portMUX_INITIALIZER_UNLOCKED 0
extern unsigned long testMillis;
inline unsigned long millis() { return testMillis; }
