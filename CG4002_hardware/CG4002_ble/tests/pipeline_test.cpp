#include "../CG4002_ble.ino"
#include <cassert>
#include <cstring>
#include <string>
#include <vector>

unsigned long testMillis=0;
struct Offered { SensorFrame frame; uint32_t burst; uint8_t event; };
std::vector<Offered> frames;
std::string status;
bool BleTelemetry::begin(const char*,uint8_t,uint32_t) { return true; }
BleLink BleTelemetry::link() const { return {1,185,true,1}; }
void BleTelemetry::enqueue(const SensorFrame& f,uint32_t b,uint8_t e) { frames.push_back({f,b,e}); }
void BleTelemetry::service() {}
void BleTelemetry::setStatus(const char* s) { status=s; }

void axes(int16_t ax,int16_t ay,int16_t az,int16_t gx,int16_t gy,int16_t gz) {
  int16_t values[]={ax,ay,az,gx,gy,gz};
  for(unsigned i=0;i<6;++i) {
    Wire.regs[0x1f+2*i]=static_cast<uint16_t>(values[i])>>8;
    Wire.regs[0x20+2*i]=values[i]&255;
  }
}
void tick() { testMicros=nextSampleUs; testMillis=testMicros/1000; loop(); }
int main(int argc,char**) {
  axes(0,0,2048,0,0,0);
  if(argc>1) {
    Wire.failDataReads=1; setup();
    assert(nodeState==FAULT && calibrationFailed && !recoverable);
    puts("PASS: failed calibration cannot stream"); return 0;
  }
  setup(); assert(nodeState==STREAMING);
  for(int i=0;i<100;++i) tick(); assert(frames.empty());
  axes(32767,-32768,32767,-32768,32767,-32768);
  for(int i=0;i<1000;++i) tick();
  assert(health.saturated==1000 && nodeState==STREAMING);
  assert(frames.front().event==1 && frames.back().frame.status_flags==15);
  assert(std::fabs(frames.front().frame.ax_filtered_g-(32767/2048.f)*.2f)<.0001f);
  auto n=frames.size(); auto seq=sequence;
  Wire.failDataReads=1; tick(); assert(sequence==seq && frames.size()==n);
  tick(); assert(!readFailed && frames.back().frame.interval_us==10000);
  axes(0,0,2048,0,0,0);
  for(int i=0;i<100;++i) tick();
  assert(!movement.isActive() && frames.back().event==2);
  n=frames.size(); for(int i=0;i<100;++i) tick(); assert(frames.size()==n);
  axes(10000,0,2048,10000,0,0); tick(); assert(movement.isActive() && burst==2);
  Wire.failDataReads=20; for(int i=0;i<20;++i) tick();
  assert(nodeState==FAULT && recoverable && !movement.isActive());
  Wire.failBegin=true; delay(1000); loop(); assert(nodeState==FAULT);
  Wire.failBegin=false; delay(1000); loop();
  assert(nodeState==STREAMING && health.recoveries==1 && burst==3);
  assert(frames.back().frame.interval_us>=2000000 && gyroCalibration.biasX==0);
  assert(status.size()<512);
  puts("PASS: actual BLE sketch acquisition, LPF, movement boundaries, saturation, read failure handling and recovery");
}
