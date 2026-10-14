#pragma once
// Host-test declarations only. Firmware always uses the installed Arduino core.
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <cmath>
#include <cstdlib>
using portMUX_TYPE = int;
#define portMUX_INITIALIZER_UNLOCKED 0
extern unsigned long testMillis;
inline unsigned long millis() { return testMillis; }
inline unsigned long testMicros = 0;
inline unsigned long micros() { return testMicros; }
inline void delay(unsigned long ms) { testMillis += ms; testMicros += ms * 1000; }
constexpr int OUTPUT = 1;
inline void analogWrite(int, int) {}
inline void pinMode(int, int) {}
struct TestSerial {
  void begin(int) {}
  int available() { return 0; }
  int read() { return -1; }
  template<class... T> void print(T...) {}
  template<class... T> void println(T...) {}
  template<class... T> void printf(const char*, T...) {}
};
inline TestSerial Serial;
