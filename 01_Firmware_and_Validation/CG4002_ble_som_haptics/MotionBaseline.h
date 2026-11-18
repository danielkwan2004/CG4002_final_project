#pragma once
#include <algorithm>
#include <vector>
#include "MotionFeatures.h"

struct FeatureReference { double median=0, mad=0, spread=0; };
struct MotionReference {
  bool valid=false;
  unsigned samples=0, rejected=0;
  uint32_t spanUs=0;
  FeatureReference gyro, accel;
};

// CP2 invokes this on the laptop after capture, from an explicitly labelled
// reference period. No ongoing adaptation and no gate decisions.
class MotionBaseline {
public:
  void add(const MotionFeatureResult& f) {
    if (finished) return;
    if (!f.valid || gyro.size()>=MotionGateConfig::BASELINE_MAX_SAMPLES) { ++rejected; return; }
    if (gyro.empty()) { first=f.timestampUs; }
    else if (f.seq-lastSeq!=1 || f.timestampUs-lastTime>MotionGateConfig::FEATURE_MAX_DT_US ||
             f.timestampUs-lastTime<MotionGateConfig::FEATURE_MIN_DT_US) ++rejected;
    lastTime=f.timestampUs; lastSeq=f.seq;
    gyro.push_back(f.gyroRmsDps); accel.push_back(f.accelRmsG);
  }
  MotionReference finish() {
    if (finished) return reference;
    finished=true;
    reference.samples=unsigned(gyro.size()); reference.rejected=rejected;
    reference.spanUs=gyro.empty()?0:lastTime-first;
    reference.valid=!rejected && gyro.size()>=MotionGateConfig::BASELINE_MIN_SAMPLES &&
                    reference.spanUs>=MotionGateConfig::BASELINE_MIN_SPAN_US;
    if (reference.valid) {
      reference.gyro=fit(gyro,MotionGateConfig::BASELINE_GYRO_SPREAD_FLOOR_DPS);
      reference.accel=fit(accel,MotionGateConfig::BASELINE_ACCEL_SPREAD_FLOOR_G);
    }
    return reference;
  }
private:
  static double median(std::vector<double> values) {
    std::sort(values.begin(),values.end());
    const auto n=values.size();
    return n%2?values[n/2]:(values[n/2-1]+values[n/2])/2;
  }
  static FeatureReference fit(const std::vector<double>& values,double floor) {
    FeatureReference r; r.median=median(values);
    std::vector<double> deviations; deviations.reserve(values.size());
    for (double v:values) deviations.push_back(fabs(v-r.median));
    r.mad=median(deviations); r.spread=std::max(floor,1.4826*r.mad); return r;
  }
  std::vector<double> gyro,accel;
  uint32_t first=0,lastTime=0,lastSeq=0;
  unsigned rejected=0;
  bool finished=false;
  MotionReference reference;
};
