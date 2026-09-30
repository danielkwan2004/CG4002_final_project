// Compile actual CaptureDiagnostics.cpp + actual queue/encoder; replace only
// clock, Wi-Fi socket and hardware declarations with deterministic host stubs.
#include "../CaptureDiagnostics.h"
#include "../SampleEncoding.h"
#include "../TelemetryScheduler.h"
#include <cassert>
#include <string>
#include <vector>

unsigned long testMillis = 0;
static TxResult nextResult = TxResult::Accepted;
static bool acceptControl = true;
static std::vector<std::string> reports;
static uint32_t controlCalls = 0, dataCalls = 0;
static std::vector<uint32_t> deliveredSequences;

bool WiFiTelemetry::sendPacket(const char* p, size_t n) {
  ++controlCalls;
  if (acceptControl) reports.emplace_back(p, n);
  return acceptControl;
}
bool WiFiTelemetry::enqueueFrame(const SensorFrame& f, uint32_t boot, uint32_t burst, uint32_t index) {
  return queue.enqueue(f, boot, burst, index, testMillis);
}
void WiFiTelemetry::service(CaptureDiagnostics& c) {
  queue.service(testMillis, encodeSample, [](const char* p, size_t n) {
        ++dataCalls;
        if (nextResult == TxResult::Accepted) {
          // Extract sequence IDs from the actual encoded rows, not counters.
          std::string packet(p, n);
          size_t start = 0;
          while (start < packet.size()) {
            size_t field = start;
            for (int i = 0; i < 5; ++i) field = packet.find(',', field) + 1;
            deliveredSequences.push_back(static_cast<uint32_t>(std::stoul(packet.substr(field))));
            start = packet.find('\n', start) + 1;
            assert(start != 0);
          }
        }
        return nextResult;
      },
      [&c](uint32_t b, uint32_t n, bool ok) { c.recordDelivery(b, n, ok); });
}
void WiFiTelemetry::cancelThrough(uint32_t b, CaptureDiagnostics& c) {
  queue.cancelThrough(b, [&c](uint32_t id, uint32_t n, bool ok) { c.recordDelivery(id, n, ok); });
}
int WiFiTelemetry::formatDiagnostics(char* p, size_t n, uint8_t, uint32_t, uint32_t) {
  return snprintf(p, n, "{\"host_test_stub\":\"transport\"}");
}
int WiFiTelemetry::formatQueueDiagnostics(char* p, size_t n, uint8_t, uint32_t, uint32_t) {
  return snprintf(p, n, "{\"host_test_stub\":\"queue\"}");
}

static SensorFrame frame(uint32_t seq) {
  SensorFrame f = {}; f.node_id = 1; f.seq = seq;
  f.timestamp_us = seq*5000; f.interval_us = 5000;
  return f;
}
static void offer(CaptureDiagnostics& c, WiFiTelemetry& w, uint32_t seq) {
  auto f = frame(seq);
  c.recordAcquisition(f.timestamp_us, 600, 0, 0);
  bool ok = w.enqueueFrame(f, 77, c.burstId(), c.burstIndex());
  c.recordQueued(f, ok);
}
static bool contains(const std::string& text, const char* part) {
  return text.find(part) != std::string::npos;
}
static std::string latest(const char* kind) {
  for (auto i = reports.rbegin(); i != reports.rend(); ++i)
    if (contains(*i, kind)) return *i;
  assert(false); return "";
}

static bool heartbeatPart(CaptureDiagnostics& c, WiFiTelemetry& w, uint32_t nowUs) {
  const ImuRegisterReadback regs = {0x44, 0x27, 0x27, 0x0f, true};
  const GyroCalibration gyro = {};
  const AccelCalibration accel = {};
  return c.serviceHeartbeat(w, nowUs, "STREAMING", 0, 1, 50, 1000,
      regs, gyro, accel, 0.2f, 400);
}

static void heartbeat(CaptureDiagnostics& c, WiFiTelemetry& w) {
  assert(c.requestHeartbeat(false));
  for (uint32_t time = 0; c.heartbeatPending(); time += 10000) {
    assert(time < 60000);
    const uint32_t before = controlCalls;
    assert(heartbeatPart(c, w, time));
    assert(controlCalls == before + 1);
  }
}

int main() {
  {
    CaptureDiagnostics c; WiFiTelemetry w; c.begin(1, 77);
    c.startBurst(frame(0));
    for (uint32_t i = 0; i < 5; ++i) { testMillis = i*5; offer(c, w, i); }
    nextResult = TxResult::Retry; w.service(c);
    c.endBurst(w);
    assert(!c.publishFinalBurst(w));
    heartbeat(c, w);
    assert(contains(latest("\"type\":\"timing\""), "\"attempted\":5,\"accepted\":0,\"failed\":0,\"pending\":5"));
    assert(contains(latest("\"type\":\"burst\""), "\"closed\":false,\"gate_closed\":true,\"pending\":5"));

    // New burst while the previous burst is still awaiting its send outcome.
    c.startBurst(frame(5)); testMillis = 25; offer(c, w, 5); c.endBurst(w);
    testMillis = 30; nextResult = TxResult::Accepted; w.service(c);
    assert(c.publishFinalBurst(w));
    assert(contains(latest("\"type\":\"burst\""), "\"id\":1,\"closed\":true"));
    assert(contains(latest("\"type\":\"burst\""), "\"attempted\":5,\"accepted\":5,\"failed\":0"));
    testMillis = 32; w.service(c);
    testMillis = 40; acceptControl = false;
    assert(c.publishFinalBurst(w)); // a rejected control send must remain dirty
    testMillis = 41; acceptControl = true;
    assert(!c.publishFinalBurst(w)); // scheduled backoff, not a tight retry loop
    testMillis = 50; assert(c.publishFinalBurst(w));
    assert(contains(latest("\"type\":\"burst\""), "\"id\":2,\"closed\":true"));
    heartbeat(c, w);
    assert(contains(latest("\"type\":\"timing\""), "\"attempted\":6,\"accepted\":6,\"failed\":0,\"pending\":0"));
  }
  {
    // Unrealistically fast bursts exercise the defensive history eviction path.
    CaptureDiagnostics c; WiFiTelemetry w; c.begin(1, 77); reports.clear();
    testMillis = 100;
    for (uint32_t i = 0; i < 9; ++i) {
      c.startBurst(frame(i)); offer(c, w, i); c.endBurst(w);
    }
    heartbeat(c, w);
    assert(contains(latest("\"type\":\"timing\""), "\"attempted\":9,\"accepted\":0,\"failed\":1,\"pending\":8"));
    for (testMillis = 1100; testMillis < 1120; ++testMillis) w.service(c);
    heartbeat(c, w);
    assert(contains(latest("\"type\":\"timing\""), "\"attempted\":9,\"accepted\":0,\"failed\":9,\"pending\":0"));
  }
  {
    TelemetryScheduler slots;
    assert(!slots.takeSlot(650, 5000, 0, true)); // no acquisition yet
    assert(!slots.takeSlot(1500, 5000, 1, true)); // exactly 3.5 ms is insufficient
    assert(!slots.takeSlot(5001, 5000, 1, true)); // deadline already missed
    assert(slots.takeSlot(5650, 10000, 2, true));
    assert(!slots.takeSlot(5700, 10000, 2, true)); // same acquisition, another loop
    assert(slots.takeSlot(10650, 15000, 3, true));
    TelemetryScheduler wrap;
    assert(wrap.takeSlot(0xfffffff0u, 0x1000u, 8, true));
    assert(!wrap.takeSlot(0x1200u, 0x1000u, 9, true));
    assert(wrap.takeSlot(0xfffffff0u, 0, 0, false));
    assert(!wrap.takeSlot(0x100u, 0, 0, false));
    assert(wrap.takeSlot(0x2000u, 0, 0, false));
  }
  {
    // All six report parts, including failure and wrap: never two socket calls.
    CaptureDiagnostics c; WiFiTelemetry w; c.begin(1, 77); reports.clear();
    testMillis = 2000; nextResult = TxResult::Accepted;
    c.startBurst(frame(0)); offer(c, w, 0); c.endBurst(w); w.service(c);
    c.startBurst(frame(1)); offer(c, w, 1);
    c.recordTelemetryCost(2400, false);
    c.recordTelemetryCost(1800, true);
    assert(c.requestHeartbeat(true));
    const uint32_t start = 0xffffd8f0u;
    for (uint32_t i = 0; i < 6; ++i) {
      uint32_t now = start + i * 10000;
      const uint32_t before = controlCalls;
      if (i) {
        assert(!heartbeatPart(c, w, now - 1));
        assert(controlCalls == before);
      }
      acceptControl = i != 2; // failed history send remains dirty
      assert(heartbeatPart(c, w, now));
      assert(controlCalls == before + 1);
      assert(!heartbeatPart(c, w, now));
      if (i < 5) assert(!c.requestHeartbeat(false)); // cannot restart pending work
    }
    acceptControl = true;
    assert(!c.heartbeatPending());
    assert(contains(latest("\"type\":\"timing\""), "\"max_wifi_us\":2400,\"max_diag_us\":1800"));
    assert(contains(latest("\"type\":\"config\""), "\"diag_scheduler\":\"staggered_v1\",\"telemetry_headroom_us\":3500"));
    assert(c.publishFinalBurst(w)); // failed history packet wasn't marked clean
    heartbeat(c, w);
    assert(contains(latest("\"type\":\"timing\""), "\"diag_failed\":1"));
  }
  {
    // 90 simulated seconds at 200 Hz, with the real queue + staggered reports.
    // This verifies scheduling/accounting, not ESP32 or RF execution timing.
    CaptureDiagnostics c; WiFiTelemetry w; TelemetryScheduler slots;
    c.begin(1, 77); reports.clear(); deliveredSequences.clear();
    nextResult = TxResult::Accepted; acceptControl = true;
    c.startBurst(frame(0));
    uint32_t nextReportUs = 1000000;
    for (uint32_t seq = 0; seq < 18000; ++seq) {
      const uint32_t now = seq * 5000 + 650;
      testMillis = now / 1000;
      offer(c, w, seq);
      if (seq == 17999) c.endBurst(w);
      assert(slots.takeSlot(now, (seq+1)*5000, seq+1, true));
      const uint32_t before = controlCalls + dataCalls;
      bool diagnostic = c.publishFinalBurst(w);
      if (!diagnostic) {
        if (now >= nextReportUs && c.requestHeartbeat(seq % 1000 == 0))
          nextReportUs = now + 1000000;
        diagnostic = heartbeatPart(c, w, now);
      }
      if (!diagnostic) w.service(c);
      assert(controlCalls + dataCalls <= before + 1);
      // Representative synthetic work costs; never claim these are measured RF.
      const uint32_t cost = diagnostic ? 1800 : 2400;
      assert(now + cost < (seq+1)*5000);
      c.recordTelemetryCost(cost, diagnostic);
      assert(!slots.takeSlot(now + cost, (seq+1)*5000, seq+1, true));
    }
    for (uint32_t i = 0; i < 20; ++i) {
      const uint32_t now = 90000000 + i * 5000;
      testMillis = now/1000;
      assert(slots.takeSlot(now, 0, 0, false));
      const uint32_t before = controlCalls + dataCalls;
      if (!c.publishFinalBurst(w) && !heartbeatPart(c, w, now)) w.service(c);
      assert(controlCalls + dataCalls <= before + 1);
    }
    assert(deliveredSequences.size() == 18000);
    for (uint32_t i = 0; i < 18000; ++i) assert(deliveredSequences[i] == i);
    heartbeat(c, w);
    assert(contains(latest("\"type\":\"timing\""), "\"attempted\":18000,\"accepted\":18000,\"failed\":0,\"pending\":0"));
    assert(contains(latest("\"type\":\"burst\""), "\"closed\":true"));
  }
  puts("PASS: actual firmware burst accounting; overlapping queued bursts; finalization after drain; control retries; history eviction; expiry settlement");
  puts("PASS: one telemetry operation per acquisition; deadline guard; clock wrap; staggered heartbeat; failed control retention; 18000 simulated samples delivered in order");
}
