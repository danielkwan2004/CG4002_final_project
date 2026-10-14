#pragma once
#include "BlePacket.h"
#include <string.h>

// Single owner: the Arduino loop. No callbacks touch this bounded queue.
class BleQueue {
public:
  static constexpr size_t CAPACITY = 128;
  uint32_t offered = 0, accepted = 0, dropped = 0, retries = 0;
  size_t pending() const { return count; }
  void clear() { dropped += static_cast<uint32_t>(count); head = count = 0; }
  void enqueue(const SensorFrame& frame, uint32_t burst, uint8_t event, uint32_t now) {
    ++offered;
    if (count == CAPACITY) { ++dropped; return; }
    items[(head + count) % CAPACITY] = {makeBleSample(frame, event), burst, now};
    ++count;
  }
  template<class Notify>
  void service(uint32_t now, uint16_t mtu, uint8_t node, uint32_t boot,
               uint32_t session, Notify notify) {
    while (count && static_cast<uint32_t>(now - items[head].queuedMs) >= 1000) {
      head = (head + 1) % CAPACITY; --count; ++dropped;
    }
    if (!count || mtu < BLE_MIN_MTU ||
        (hasAttempt && static_cast<uint32_t>(now-lastAttempt) < waitMs)) return;
    size_t limit = (mtu - 3 - sizeof(BleHeader)) / sizeof(BleSample);
    if (limit > BLE_BATCH_SIZE) limit = BLE_BATCH_SIZE;
    size_t n = 0;
    bool boundary = false;
    const uint32_t burst = items[head].burst;
    while (n < count && n < limit) {
      const Item& item = items[(head+n) % CAPACITY];
      if (item.burst != burst) { boundary = true; break; }
      ++n;
      if (item.sample.event & 2) { boundary = true; break; }
    }
    if (n < limit && !boundary && static_cast<uint32_t>(now-items[head].queuedMs) < 20) return;
    uint8_t packet[BLE_PACKET_BYTES];
    BleHeader header;
    header.node = node; header.boot = boot; header.session = session;
    header.burst = burst; header.count = static_cast<uint8_t>(n);
    memcpy(packet, &header, sizeof(header));
    for (size_t i=0; i<n; ++i)
      memcpy(packet + sizeof(header) + i*sizeof(BleSample),
             &items[(head+i) % CAPACITY].sample, sizeof(BleSample));
    hasAttempt = true; lastAttempt = now;
    if (notify(packet, sizeof(header) + n*sizeof(BleSample))) {
      head = (head+n) % CAPACITY; count -= n; accepted += static_cast<uint32_t>(n);
      waitMs = 2;
    } else { ++retries; waitMs = 10; }
  }
private:
  struct Item { BleSample sample; uint32_t burst, queuedMs; };
  Item items[CAPACITY] = {};
  size_t head = 0, count = 0;
  bool hasAttempt = false;
  uint32_t lastAttempt = 0, waitMs = 2;
};
