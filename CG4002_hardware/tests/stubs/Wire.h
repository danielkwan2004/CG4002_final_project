#pragma once
#include <stdint.h>
#include <stddef.h>
#include <vector>
class TwoWire {
public:
  uint8_t regs[256] = {};
  int failDataReads = 0;
  int shortBytes = 0;
  uint8_t writeError = 0;
  bool failBegin = false;
  unsigned begins = 0;
  std::vector<uint8_t> tx, rx;
  size_t index = 0;
  uint8_t reg = 0;
  TwoWire() { regs[0x75] = 0x44; }
  bool begin(int, int, uint32_t = 100000) { ++begins; return !failBegin; }
  bool end() { return true; }
  void setClock(uint32_t) {}
  void setTimeOut(uint16_t) {}
  void beginTransmission(uint8_t) { tx.clear(); }
  size_t write(uint8_t value) { tx.push_back(value); return 1; }
  uint8_t endTransmission(bool = true) {
    if (writeError) return writeError;
    reg = tx.at(0);
    if (tx.size() == 2) regs[reg] = tx[1];
    return 0;
  }
  size_t requestFrom(uint8_t, size_t n) {
    rx.clear(); index = 0;
    if (reg == 0x1f && failDataReads) { --failDataReads; n = shortBytes; }
    for (size_t i = 0; i < n; ++i) rx.push_back(regs[reg+i]);
    return n;
  }
  int available() { return static_cast<int>(rx.size() - index); }
  int read() { return available() ? rx[index++] : -1; }
};
inline TwoWire Wire;
