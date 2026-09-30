#ifndef TX_QUEUE_H
#define TX_QUEUE_H

#include "SensorFrame.h"
#include <stddef.h>

// Portable, allocation-free queue; the same implementation is exercised by
// host C++ fault-injection tests. One service call makes at most one send call.
enum class TxResult { Accepted, Retry, PermanentFailure };

struct QueuedSample {
  SensorFrame frame;
  uint32_t boot, burst, index, enqueuedMs;
};

struct TxQueueCounters {
  uint32_t offered = 0, accepted = 0, dropped = 0, recovered = 0;
  uint32_t overflow = 0, expired = 0, permanent = 0, cancelled = 0;
  uint32_t calls = 0, errors = 0, retries = 0, datagrams = 0;
  uint32_t highWater = 0, maxAgeMs = 0;
};

class TxQueue {
public:
  static constexpr size_t CAPACITY = 128;
  static constexpr size_t BATCH_SIZE = 5;
  static constexpr size_t PACKET_BYTES = 1400;  // below normal IPv4 UDP MTU
  static constexpr uint32_t FLUSH_MS = 20;
  static constexpr uint32_t MAX_AGE_MS = 1000;
  static constexpr uint32_t RETRY_MS = 10;
  static constexpr uint32_t SEND_GAP_MS = 2;

  bool enqueue(const SensorFrame& frame, uint32_t boot, uint32_t burst,
               uint32_t index, uint32_t nowMs) {
    ++stats.offered;
    if (count == CAPACITY) {
      ++stats.overflow;
      ++stats.dropped;
      return false;
    }
    entries[(head + count) % CAPACITY] = {frame, boot, burst, index, nowMs};
    ++count;
    if (count > stats.highWater) stats.highWater = static_cast<uint32_t>(count);
    return true;
  }

  void closeBurst(uint32_t burst) { closedThrough = burst; }
  size_t pending() const { return count; }
  const TxQueueCounters& counters() const { return stats; }
  uint32_t oldestAgeMs(uint32_t now) const {
    return count ? static_cast<uint32_t>(now - entries[head].enqueuedMs) : 0;
  }

  // Encoder returns snprintf-style length, Sender returns TxResult, and
  // Completed(burst, sampleCount, accepted) settles each sample exactly once.
  template<class Encoder, class Sender, class Completed>
  void service(uint32_t now, Encoder encode, Sender send, Completed completed) {
    if (!count) return;
    const uint32_t age = oldestAgeMs(now);
    if (age > stats.maxAgeMs) stats.maxAgeMs = age;
    if (age >= MAX_AGE_MS) {
      const size_t n = batchCount ? batchCount : 1;
      stats.expired += static_cast<uint32_t>(n);
      finish(n, false, completed);
      return;
    }
    // Difference arithmetic survives millis wrap; no sleeps or retry loops.
    if (hasSent && static_cast<uint32_t>(now - lastCallMs) < waitMs) return;
    if (!batchCount) {
      const uint32_t burst = entries[head].burst;
      bool boundary = burst <= closedThrough;
      for (size_t i = 1; i < count && i < BATCH_SIZE; ++i)
        boundary |= entries[(head + i) % CAPACITY].burst != burst;
      if (count < BATCH_SIZE && age < FLUSH_MS && !boundary) return;
      packetLength = 0;
      for (size_t i = 0; i < count && i < BATCH_SIZE; ++i) {
        const QueuedSample& item = entries[(head + i) % CAPACITY];
        if (item.burst != burst) break;  // never mix burst accounting
        const size_t room = sizeof(packet) - packetLength;
        int length = encode(item, packet + packetLength, room);
        if (length <= 0 || static_cast<size_t>(length) >= room) {
          if (!batchCount) {
            ++stats.permanent;
            finish(1, false, completed);
            return;
          }
          break;  // smaller batch, not an oversized/truncated datagram
        }
        packetLength += length;
        ++batchCount;
      }
    }
    if (batchHadError) ++stats.retries;
    ++stats.calls;
    hasSent = true;
    lastCallMs = now;
    TxResult result = send(packet, packetLength);
    waitMs = result == TxResult::Retry ? RETRY_MS : SEND_GAP_MS;
    if (result == TxResult::Accepted) {
      ++stats.datagrams;
      if (batchHadError) stats.recovered += static_cast<uint32_t>(batchCount);
      finish(batchCount, true, completed);
    } else {
      ++stats.errors;
      batchHadError = true;
      if (result == TxResult::PermanentFailure) {
        stats.permanent += static_cast<uint32_t>(batchCount);
        finish(batchCount, false, completed);
      }
      // Retry keeps the exact datagram, sample IDs and acquisition timestamps.
    }
  }

  // Defensive history-eviction path. Never lose unfinalized sender accounting.
  template<class Completed>
  void cancelThrough(uint32_t burst, Completed completed) {
    while (count && entries[head].burst <= burst) {
      ++stats.cancelled;
      finish(1, false, completed);
    }
  }

private:
  template<class Completed>
  void finish(size_t n, bool accepted, Completed completed) {
    uint32_t burst = entries[head].burst;
    if (accepted) stats.accepted += static_cast<uint32_t>(n);
    else stats.dropped += static_cast<uint32_t>(n);
    head = (head + n) % CAPACITY;
    count -= n;
    batchCount = 0;
    packetLength = 0;
    batchHadError = false;
    completed(burst, static_cast<uint32_t>(n), accepted);
  }

  QueuedSample entries[CAPACITY] = {};
  char packet[PACKET_BYTES] = {};
  size_t head = 0, count = 0, batchCount = 0, packetLength = 0;
  uint32_t closedThrough = 0, lastCallMs = 0, waitMs = SEND_GAP_MS;
  bool hasSent = false, batchHadError = false;
  TxQueueCounters stats;
};

#endif
