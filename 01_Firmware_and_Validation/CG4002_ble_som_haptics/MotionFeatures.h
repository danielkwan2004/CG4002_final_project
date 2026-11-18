#pragma once
#include <stdint.h>
#include <math.h>
#include "MotionGateConfig.h"

struct MotionFeatureResult {
  uint32_t seq=0, timestampUs=0, resets=0;
  unsigned count=0;
  bool valid=false;
  float gyroRmsDps=0, accelRmsG=0;
};

// Input is already calibrated and alpha-filtered. Never filter it a second time.
// Uses unsigned device time differences, including micros()/sequence wrap.
class MotionFeatures {
public:
  void invalidate() {
    count=write=0; havePrevious=false; last.valid=false; last.count=0;
    last.gyroRmsDps=last.accelRmsG=0;
  }
  const MotionFeatureResult& update(uint32_t seq, uint32_t timestamp,
      float ax, float ay, float az, float gx, float gy, float gz, bool usable=true) {
    if (havePrevious && (seq-previousSeq!=1 || timestamp-previousTime<MotionGateConfig::FEATURE_MIN_DT_US ||
                        timestamp-previousTime>MotionGateConfig::FEATURE_MAX_DT_US)) {
      ++last.resets; invalidate();
    }
    last.seq=seq; last.timestampUs=timestamp;
    if (!usable || !isfinite(ax) || !isfinite(ay) || !isfinite(az) ||
                   !isfinite(gx) || !isfinite(gy) || !isfinite(gz)) {
      ++last.resets; invalidate(); return last;
    }
    havePrevious=true; previousSeq=seq; previousTime=timestamp;
    const double deviation=sqrt(double(ax)*ax+double(ay)*ay+double(az)*az)-1.0;
    gyroSquared[write]=double(gx)*gx+double(gy)*gy+double(gz)*gz;
    accelSquared[write]=deviation*deviation;
    write=(write+1)%MotionGateConfig::FEATURE_WINDOW_SAMPLES;
    if (count<MotionGateConfig::FEATURE_WINDOW_SAMPLES) ++count;
    last.count=count; last.valid=count==MotionGateConfig::FEATURE_WINDOW_SAMPLES;
    last.gyroRmsDps=last.accelRmsG=0;
    if (last.valid) {
      double g=0,a=0;
      for (unsigned i=0;i<count;++i) { g+=gyroSquared[i]; a+=accelSquared[i]; }
      last.gyroRmsDps=float(sqrt(g/count)); last.accelRmsG=float(sqrt(a/count));
    }
    return last;
  }
  const MotionFeatureResult& result() const { return last; }
private:
  double gyroSquared[MotionGateConfig::FEATURE_WINDOW_SAMPLES]={};
  double accelSquared[MotionGateConfig::FEATURE_WINDOW_SAMPLES]={};
  unsigned count=0,write=0;
  uint32_t previousSeq=0,previousTime=0;
  bool havePrevious=false;
  MotionFeatureResult last;
};
