#include "../SampleEncoding.h"
#include <cassert>
#include <cstdio>
#include <string>
#include <vector>
#include <map>

static SensorFrame frame(uint32_t n) {
  SensorFrame f = {};
  f.node_id = 1; f.seq = n; f.timestamp_us = n * 5000;
  f.interval_us = 5000; f.az = 2048; f.az_g = f.az_filtered_g = 1;
  f.status_flags = 14;
  return f;
}

static void balanced(const TxQueue& q) {
  const auto& s = q.counters();
  assert(s.offered == s.accepted + s.dropped + q.pending());
  assert(s.dropped == s.overflow + s.expired + s.permanent + s.cancelled);
  assert(s.calls == s.datagrams + s.errors);
  assert(s.recovered <= s.accepted);
  assert(q.pending() <= TxQueue::CAPACITY);
}

static void steady_and_transient(bool inject) {
  TxQueue q;
  uint32_t accepted = 0, lost = 0, lastCall = 0;
  bool wasError = false;
  std::string failedPacket;
  std::vector<std::string> delivered;
  auto completed = [&](uint32_t burst, uint32_t n, bool ok) {
    assert(burst == 1);
    (ok ? accepted : lost) += n;
  };
  for (uint32_t ms = 0; ms < 11000; ++ms) {
    if (ms < 10000 && ms % 5 == 0) assert(q.enqueue(frame(ms/5), 77, 1, ms/5, ms));
    if (ms == 10000) q.closeBurst(1);
    q.service(ms, encodeSample, [&](const char* p, size_t n) {
      assert(n < TxQueue::PACKET_BYTES);
      if (wasError) {
        assert(ms - lastCall >= TxQueue::RETRY_MS);
        assert(std::string(p, n) == failedPacket);
      }
      lastCall = ms;
      bool fail = inject && ((ms >= 1000 && ms < 1240) || (ms >= 3000 && ms < 3500));
      wasError = fail;
      if (fail) { failedPacket.assign(p, n); return TxResult::Retry; }
      delivered.emplace_back(p, n);
      return TxResult::Accepted;
    }, completed);
    balanced(q);
  }
  assert(accepted == 2000 && lost == 0 && q.pending() == 0);
  assert(q.counters().dropped == 0);
  size_t rows = 0;
  uint32_t expected = 0;
  for (const auto& packet : delivered) {
    size_t begin = 0;
    while (begin < packet.size()) {
      size_t end = packet.find('\n', begin);
      assert(end != std::string::npos);
      unsigned long boot, burst, index, seq, timestamp;
      unsigned version, node;
      assert(sscanf(packet.c_str()+begin, "%u,%u,%lu,%lu,%lu,%lu,%lu", &version, &node,
                    &boot, &burst, &index, &seq, &timestamp) == 7);
      assert(version == 4 && node == 1 && boot == 77 && burst == 1);
      assert(index == expected && seq == expected && timestamp == expected * 5000);
      ++expected; ++rows; begin = end+1;
    }
  }
  assert(rows == 2000);
  if (inject) { assert(q.counters().retries > 0 && q.counters().recovered > 0); }
  else { assert(q.counters().datagrams == 400 && q.counters().retries == 0); }
}

static void outages_are_bounded() {
  TxQueue q;
  uint32_t settledDrops = 0, rejected = 0;
  for (uint32_t ms = 0; ms < 3500; ++ms) {
    if (ms < 2000 && ms % 5 == 0)
      if (!q.enqueue(frame(ms/5), 77, 1, ms/5, ms)) ++rejected;
    q.service(ms, encodeSample, [](const char*, size_t) { return TxResult::Retry; },
        [&](uint32_t, uint32_t n, bool ok) { assert(!ok); settledDrops += n; });
    balanced(q);
  }
  assert(q.pending() == 0 && q.counters().accepted == 0);
  assert(q.counters().offered == 400 && q.counters().dropped == 400);
  assert(q.counters().overflow > 0 && q.counters().expired > 0);
  assert(settledDrops + rejected == 400);
  assert(q.counters().calls < 350); // backoff, not a busy retry loop
}

static void boundaries_wrap_and_permanent_errors() {
  TxQueue q;
  std::map<uint32_t, uint32_t> accepted;
  auto done = [&](uint32_t b, uint32_t n, bool ok) { assert(ok); accepted[b] += n; };
  q.enqueue(frame(0), 77, 1, 0, 0xfffffff0U);
  q.service(0xfffffff5U, encodeSample, [](const char*, size_t) {
    assert(false); return TxResult::Accepted;
  }, done);
  q.service(5, encodeSample, [](const char*, size_t) { return TxResult::Accepted; }, done);
  assert(accepted[1] == 1 && q.counters().maxAgeMs == 21);
  q.enqueue(frame(1), 77, 2, 0, 10);
  q.enqueue(frame(2), 77, 3, 0, 10);
  q.service(10, encodeSample, [](const char*, size_t) { return TxResult::Accepted; }, done);
  assert(accepted[2] == 1 && q.pending() == 1);
  q.closeBurst(3);
  q.service(12, encodeSample, [](const char*, size_t) { return TxResult::Accepted; }, done);
  assert(accepted[3] == 1 && q.pending() == 0);
  q.enqueue(frame(3), 77, 4, 0, 13);
  q.closeBurst(4);
  q.service(14, encodeSample, [](const char*, size_t) { return TxResult::PermanentFailure; },
      [](uint32_t b, uint32_t n, bool ok) { assert(b == 4 && n == 1 && !ok); });
  assert(q.counters().permanent == 1);
  q.enqueue(frame(4), 77, 5, 0, 15);
  q.closeBurst(5);
  q.service(16, [](const QueuedSample&, char*, size_t) { return 5000; },
      [](const char*, size_t) { assert(false); return TxResult::Accepted; },
      [](uint32_t b, uint32_t n, bool ok) { assert(b == 5 && n == 1 && !ok); });
  assert(q.counters().permanent == 2);
  q.enqueue(frame(5), 77, 6, 0, 17);
  q.enqueue(frame(6), 77, 7, 0, 17);
  q.cancelThrough(6, [](uint32_t b, uint32_t n, bool ok) { assert(b == 6 && n == 1 && !ok); });
  assert(q.pending() == 1 && q.counters().cancelled == 1);
  balanced(q);
}

int main() {
  steady_and_transient(false);
  steady_and_transient(true);
  outages_are_bounded();
  boundaries_wrap_and_permanent_errors();
  puts("PASS: steady 200 Hz; transient recovery; immutable retries; bounded outage/overflow/expiry; burst flush; clock wrap; permanent/format errors; history eviction");
}
