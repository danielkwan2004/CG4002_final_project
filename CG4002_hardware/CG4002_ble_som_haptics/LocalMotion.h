#pragma once
#include "MotionFeatures.h"
#include "MotionBaseline.h"
#include "ShadowDetector.h"
#include "SensorFrame.h"

// Startup procedure only; detector thresholds/timing remain in NodeConfig.h and
// MotionGateConfig.h. Reference fitting is the accepted median/MAD calculation.
namespace BleMotionSetup {
constexpr uint32_t SETTLE_MS = 10000;
constexpr uint32_t REFERENCE_MS = 12000;
}

class LocalMotion {
public:
  MotionFeatures features;
  ShadowDetector detector;
  uint32_t referenceAttempts=0, referenceFailures=0, started=0, ended=0;
  uint32_t selected=0, fallback=0, clippedOverlap=0, excludedInvalid=0;
  bool enabled=false, collecting=false, open=false, justEnded=false;

  bool armed() const { return detector.nonce != 0; }
  void suspend() {
    enabled=false; collecting=false; open=false; justEnded=false;
    head=size=0; features.invalidate(); detector.interrupt();
    baseline=MotionBaseline();
  }
  template<class Sink> void process(const SensorFrame& frame, uint32_t sampleMs, Sink sink) {
    justEnded=false;
    if (!enabled) { enabled=true; begunMs=sampleMs; }
    const bool usable=(frame.status_flags&7)==6;
    auto f=features.update(frame.seq,uint32_t(frame.timestamp_us),
        frame.ax_filtered_g,frame.ay_filtered_g,frame.az_filtered_g,
        frame.gx_filtered_dps,frame.gy_filtered_dps,frame.gz_filtered_dps,usable);
    if (!armed()) {
      const uint32_t age=sampleMs-begunMs;
      if (age<BleMotionSetup::SETTLE_MS) return;
      if (!collecting) { collecting=true; ++referenceAttempts; }
      const uint32_t relative=age-BleMotionSetup::SETTLE_MS;
      if (relative>=MotionGateConfig::BASELINE_TRIM_MS &&
          relative<BleMotionSetup::REFERENCE_MS-MotionGateConfig::BASELINE_TRIM_MS)
        baseline.add(f);
      if (relative<BleMotionSetup::REFERENCE_MS) return;
      const auto r=baseline.finish();
      ShadowReference reference{float(r.gyro.median),float(r.gyro.spread),
                                float(r.accel.median),float(r.accel.spread)};
      if (!r.valid || !detector.install(1,reference)) {
        ++referenceFailures; begunMs=sampleMs; collecting=false; baseline=MotionBaseline();
        return; // retry the same supported reference procedure; never invent thresholds
      }
      baseline=MotionBaseline(); collecting=false;
    }
    const auto motionState=detector.update(f);
    if (!usable) { ++excludedInvalid; return; } // packet has no quality field
    const bool active=motionState==ShadowState::Active || motionState==ShadowState::Ending;
    const bool unknown=motionState==ShadowState::Invalid;
    if (active && !open) {
      open=true; ++started;
      for (unsigned i=0;i<size;++i) {
        const auto& old=history[(head+i)%CAPACITY];
        if (uint32_t(frame.timestamp_us-old.frame.timestamp_us)<=MotionGateConfig::SEGMENT_HISTORY_US)
          emit(old.frame,old.timestampMs,sink);
      }
    }
    if (open || unknown) {
      emit(frame,sampleMs,sink);
      if (unknown) ++fallback;
      if (open && motionState==ShadowState::Background) { open=false; justEnded=true; ++ended; }
    }
    if (size<CAPACITY) history[(head+size++)%CAPACITY]={frame,sampleMs};
    else { history[head]={frame,sampleMs}; head=(head+1)%CAPACITY; }
  }
private:
  static constexpr unsigned CAPACITY=MotionGateConfig::SEGMENT_HISTORY_SAMPLES;
  struct Stored { SensorFrame frame; uint32_t timestampMs; };
  Stored history[CAPACITY]={};
  MotionBaseline baseline;
  unsigned head=0,size=0;
  uint32_t begunMs=0,lastSelected=0;
  bool haveSelected=false;
  template<class Sink> void emit(const SensorFrame& f,uint32_t ms,Sink sink) {
    if (haveSelected && int32_t(f.seq-lastSelected)<=0) { ++clippedOverlap; return; }
    sink(f,ms); lastSelected=f.seq; haveSelected=true; ++selected;
  }
};
