#include "../BleQueue.h"
#include <cassert>
#include <cstdio>
#include <vector>

int main() {
  SensorFrame f = {}; f.status_flags = 14; f.ax_filtered_g = 1.25f;
  f.gx_filtered_dps = -123.5f;
  BleQueue q;
  std::vector<uint8_t> packet;
  unsigned calls = 0;
  auto send = [&](const uint8_t* p, size_t n) { ++calls; packet.assign(p,p+n); return true; };
  for (unsigned i=0;i<4;++i) { f.seq=i; q.enqueue(f,1,i==0?1:0,i*5); }
  q.service(15,23,1,77,2,send); assert(calls==0); // default MTU cannot fit one
  q.service(15,185,1,77,2,send);
  assert(calls==1 && packet.size()==170 && q.accepted==4 && q.pending()==0);
  BleHeader h; BleSample s;
  memcpy(&h,packet.data(),sizeof(h)); memcpy(&s,packet.data()+sizeof(h),sizeof(s));
  assert(h.count==4 && h.session==2 && h.burst==1 && s.ax==1.25f && s.gx==-123.5f && s.event==1);
  // Write a C++-encoded fixture for the Python decoder (same host endian as ESP32).
  FILE* fixture=nullptr; fopen_s(&fixture,"ble_packet.bin","wb"); assert(fixture);
  fwrite(packet.data(),1,packet.size(),fixture); fclose(fixture);
  f.seq=4; q.enqueue(f,1,2,20); q.service(20,185,1,77,2,send);
  assert(calls==2 && q.accepted==5); // immediate short end batch
  f.seq=5; q.enqueue(f,2,1,25); f.seq=6; q.enqueue(f,3,1,30);
  q.service(30,185,1,77,2,send); assert(q.pending()==1);
  memcpy(&h,packet.data(),sizeof(h)); assert(h.count==1 && h.burst==2);
  q.service(35,59,1,77,2,send); assert(q.pending()==0 && packet.size()==56);
  q.enqueue(f,4,0,40);
  unsigned failures=0;
  auto fail=[&](const uint8_t*,size_t) { ++failures; return false; };
  q.service(60,185,1,77,2,fail); q.service(65,185,1,77,2,fail);
  assert(failures==1 && q.retries==1 && q.pending()==1);
  q.service(70,185,1,77,2,send); assert(q.pending()==0);
  for (unsigned i=0;i<130;++i) q.enqueue(f,5,0,100);
  assert(q.pending()==128 && q.dropped==2);
  q.service(1100,185,1,77,2,send); assert(q.pending()==0 && q.dropped==130);
  q.enqueue(f,6,0,1200); q.clear(); assert(q.dropped==131);
  assert(q.offered==q.accepted+q.dropped+q.pending());
  BleQueue wrap;
  wrap.enqueue(f,1,0,0xfffffff0u);
  wrap.service(10,185,1,77,2,send); assert(wrap.accepted==1);
  puts("PASS: wire layout, MTU sizes, batching, tail flush, burst isolation, retry backoff, overflow, expiry, clear accounting, clock wrap");
}
