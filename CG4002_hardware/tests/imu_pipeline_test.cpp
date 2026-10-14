// Execute the ACTUAL sketch loop, driver, filters, gate and capture accounting.
// Only Arduino/Wire and Wi-Fi socket I/O are replaced. No hardware claims.
#include "../CG4002_hardware.ino"
#include "../SampleEncoding.h"
#include <cassert>
#include <cstring>
#include <string>
#include <vector>

unsigned long testMillis = 0;
std::vector<SensorFrame> offered;
std::vector<std::string> reports;
bool WiFiTelemetry::begin(const char*, const char*, const char*, uint16_t) { return true; }
IPAddress WiFiTelemetry::localIP() const { return {}; }
bool WiFiTelemetry::sendPacket(const char* p, size_t n) { reports.emplace_back(p,n); return true; }
bool WiFiTelemetry::sendFrame(const SensorFrame&, uint32_t, uint32_t, uint32_t) { return true; }
bool WiFiTelemetry::enqueueFrame(const SensorFrame& f, uint32_t b, uint32_t id, uint32_t i) {
  offered.push_back(f); return queue.enqueue(f,b,id,i,millis());
}
void WiFiTelemetry::service(CaptureDiagnostics& c) {
  queue.service(millis(), encodeSample, [](const char*, size_t) { return TxResult::Accepted; },
      [&c](uint32_t b, uint32_t n, bool ok) { c.recordDelivery(b,n,ok); });
}
void WiFiTelemetry::cancelThrough(uint32_t b, CaptureDiagnostics& c) {
  queue.cancelThrough(b,[&c](uint32_t id,uint32_t n,bool ok) { c.recordDelivery(id,n,ok); });
}
int WiFiTelemetry::formatDiagnostics(char* p,size_t n,uint8_t,uint32_t,uint32_t) { return snprintf(p,n,"{}"); }
int WiFiTelemetry::formatQueueDiagnostics(char* p,size_t n,uint8_t,uint32_t,uint32_t) { return snprintf(p,n,"{}"); }

void axes(int16_t ax,int16_t ay,int16_t az,int16_t gx,int16_t gy,int16_t gz) {
  const int16_t values[] = {ax,ay,az,gx,gy,gz};
  for (unsigned i=0;i<6;++i) {
    Wire.regs[0x1f+2*i] = static_cast<uint16_t>(values[i]) >> 8;
    Wire.regs[0x20+2*i] = values[i] & 255;
  }
}
void tick() { testMicros = nextSampleTime; testMillis = testMicros/1000; loop(); }
bool containsReport(const char* part) {
  for (const auto& r:reports) if (r.find(part)!=std::string::npos) return true;
  return false;
}
int main(int argc,char** argv) {
  axes(0,0,2048,0,0,0);
  if (argc>1 && std::strcmp(argv[1],"calibration-failure")==0) {
    Wire.failDataReads=1; setup();
    assert(nodeState==NODE_FAULT && calibrationReadFailed && !runtimeImuFault);
    delay(2000); loop(); assert(nodeState==NODE_FAULT); // never use bad bias
    puts("PASS: failed calibration cannot silently become valid"); return 0;
  }
  setup(); assert(nodeState==NODE_STREAMING);
  for (int i=0;i<40;++i) tick();
  assert(offered.empty());
  axes(32767,-32768,32767,-32768,32767,-32768);
  for (int i=0;i<1000;++i) tick();
  assert(nodeState==NODE_STREAMING && imuHealth.saturated==1000);
  assert(!offered.empty());
  assert(std::fabs(offered.front().ax_filtered_g-(32767/2048.0f)*0.2f)<0.0001f);
  const auto peak=offered.back();
  assert(peak.ax==32767 && peak.ay==-32768 && peak.gx==-32768);
  assert(peak.status_flags==15); // valid, calibrated, active, saturated
  assert(std::fabs(peak.gx_filtered_dps-(-32768/16.4f))<0.1f);
  assert(peak.interval_us==5000);

  const uint32_t seq=nextSeq; const size_t count=offered.size();
  Wire.failDataReads=1; Wire.shortBytes=7; tick();
  assert(nodeState==NODE_STREAMING && nextSeq==seq && offered.size()==count);
  assert(imuHealth.readFailures==1 && Wire.available()==0);
  assert(imu.lastError().received==7 && imu.lastError().expected==12);
  tick(); assert(nextSeq==seq+1 && imuHealth.consecutive==0 && !imuReadFault);
  assert(offered.back().interval_us==10000);

  // Quiet gaps cannot count as observed quiet. This tests gate behavior too.
  MoveDetector gate; assert(gate.update(100,0,0)==MOVE_EVENT_STARTED);
  gate.update(0,0,10); gate.interruptQuietWindow();
  assert(gate.update(0,0,200)==MOVE_EVENT_NONE);
  assert(gate.update(0,0,349)==MOVE_EVENT_NONE);
  assert(gate.update(0,0,350)==MOVE_EVENT_ENDED);

  Wire.failDataReads=20; Wire.shortBytes=0;
  for (int i=0;i<20;++i) tick();
  assert(nodeState==NODE_FAULT && runtimeImuFault && !moveDetector.isActive());
  assert(imuHealth.consecutive==20);
  loop(); assert(imuHealth.recoveryAttempts==0);
  Wire.failBegin=true; delay(1000); loop();
  assert(nodeState==NODE_FAULT && imuHealth.recoveryAttempts==1);
  Wire.failBegin=false;
  Wire.regs[0x75]=0; delay(1000); loop();
  assert(nodeState==NODE_FAULT && imuHealth.recoveryAttempts==2);
  Wire.regs[0x75]=0x44; delay(1000); loop();
  assert(nodeState==NODE_STREAMING && imuHealth.recoveries==1);
  assert(gyroCalibration.biasX==0 && accelCalibration.offsetZ_g==0);
  // Do not reset virtual time to the expired deadline after recovery.
  loop(); assert(offered.back().interval_us>=3000000);
  assert(moveDetector.isActive());
  axes(0,0,2048,0,0,0);
  for (int i=0;i<100;++i) tick();
  assert(!moveDetector.isActive() && nodeState==NODE_STREAMING);
  const size_t stopped=offered.size();
  for (int i=0;i<400;++i) tick();
  assert(offered.size()==stopped);
  assert(containsReport("\"interrupted\":true"));
  assert(containsReport("\"imu_read_failures\":21"));
  assert(containsReport("\"imu_recoveries\":1"));
  assert(containsReport("\"saturated_samples\":"));
  // Address-stage failure must leave the caller's frame untouched as well.
  SensorFrame sentinel = {}; sentinel.ax = 123;
  Wire.writeError=2;
  assert(!imu.readRaw(sentinel) && sentinel.ax==123);
  assert(imu.lastError().wireStatus==2);
  Wire.writeError=0;
  assert(imu.readRaw(sentinel) && sentinel.az==2048);
  assert(imu.lastError().wireStatus==2); // preserve last failed transaction
  puts("PASS: actual sketch at full-scale extremes; movement/quiet gating; short-read discard; next-slot recovery; sustained outage; repeated recovery; retained calibration; interruption and health telemetry");
}
