#pragma once
#include "MotionFeatures.h"
#include <stdio.h>
#include <string.h>

// Encoded in status_flags bits 5..7; low five bits keep their original meaning.
enum class ShadowState : uint8_t { Disarmed=0, Background=1, Candidate=2, Active=3, Ending=4, Invalid=5 };
struct ShadowReference { float gyroB=0,gyroS=0,accelB=0,accelS=0; };
struct ShadowThresholds { float gyroStart=0,accelStart=0,gyroStop=0,accelStop=0; };

class ShadowDetector {
public:
  bool install(uint32_t id,const ShadowReference& r) {
    if (!id) return false;
    if (nonce) return nonce==id && r.gyroB==reference.gyroB && r.gyroS==reference.gyroS &&
        r.accelB==reference.accelB && r.accelS==reference.accelS; // retry never restarts detector
    using namespace MotionGateConfig;
    if (!isfinite(r.gyroB)||!isfinite(r.gyroS)||!isfinite(r.accelB)||!isfinite(r.accelS) ||
        r.gyroB<0 || r.gyroB>4000 || r.gyroS<BASELINE_GYRO_SPREAD_FLOOR_DPS || r.gyroS>4000 ||
        r.accelB<0 || r.accelB>32 || r.accelS<BASELINE_ACCEL_SPREAD_FLOOR_G || r.accelS>32) return false;
    thresholds={fmaxf(SHADOW_START_GYRO_FLOOR_DPS,r.gyroB+SHADOW_START_K*r.gyroS),
                fmaxf(SHADOW_START_ACCEL_FLOOR_G,r.accelB+SHADOW_START_K*r.accelS),
                fmaxf(SHADOW_STOP_GYRO_FLOOR_DPS,r.gyroB+SHADOW_STOP_K*r.gyroS),
                fmaxf(SHADOW_STOP_ACCEL_FLOOR_G,r.accelB+SHADOW_STOP_K*r.accelS)};
    if (!(thresholds.gyroStop<thresholds.gyroStart && thresholds.accelStop<thresholds.accelStart)) return false;
    reference=r; nonce=id; return true;
  }
  // Only a single, boot-scoped reference is accepted. A fresh run needs a reset.
  bool command(const char* text,uint32_t boot) {
    unsigned long long b=0,n=0; ShadowReference r; char tail;
    if (sscanf(text,"SOM3 %llu %llu %f %f %f %f %c",&b,&n,
        &r.gyroB,&r.gyroS,&r.accelB,&r.accelS,&tail)!=6 || b!=boot || n>UINT32_MAX) return false;
    return install(uint32_t(n),r);
  }
  void interrupt() {
    if (!nonce) return;
    if (state==ShadowState::Candidate || state==ShadowState::Active || state==ShadowState::Ending) ++interruptions;
    state=ShadowState::Invalid; havePrevious=false;
  }
  ShadowState update(const MotionFeatureResult& f) {
    seq=f.seq; timestamp=f.timestampUs;
    if (!nonce) return state;
    if (!activated) { activated=true; activationSeq=f.seq; }
    if (!f.valid || (havePrevious && (f.seq-previousSeq!=1 ||
        f.timestampUs-previousTime<MotionGateConfig::FEATURE_MIN_DT_US ||
        f.timestampUs-previousTime>MotionGateConfig::FEATURE_MAX_DT_US))) {
      interrupt(); return state;
    }
    havePrevious=true; previousSeq=f.seq; previousTime=f.timestampUs;
    const bool high=f.gyroRmsDps>thresholds.gyroStart || f.accelRmsG>thresholds.accelStart;
    const bool quiet=f.gyroRmsDps<thresholds.gyroStop && f.accelRmsG<thresholds.accelStop;
    if (state==ShadowState::Disarmed || state==ShadowState::Invalid) state=ShadowState::Background;
    switch(state) {
      case ShadowState::Background:
        if (high) { state=ShadowState::Candidate; candidateUs=f.timestampUs; ++candidates; }
        break;
      case ShadowState::Candidate:
        if (!high) { state=ShadowState::Background; ++cancelled; }
        else if (f.timestampUs-candidateUs>=MotionGateConfig::SHADOW_CONFIRM_US) { state=ShadowState::Active; ++starts; }
        break;
      case ShadowState::Active:
        if (quiet) { state=ShadowState::Ending; quietUs=f.timestampUs; }
        break;
      case ShadowState::Ending:
        if (!quiet) state=ShadowState::Active;
        else if (f.timestampUs-quietUs>=MotionGateConfig::SHADOW_QUIET_US) { state=ShadowState::Background; ++ends; }
        break;
      default: break;
    }
    return state;
  }
  void recordCost(uint32_t us) { if(us>maxComputeUs) maxComputeUs=us; }
  int format(char* out,size_t capacity,uint8_t node,uint32_t boot,uint32_t produced) const {
    using namespace MotionGateConfig;
    return snprintf(out,capacity,
      "{\"v\":4,\"type\":\"shadow\",\"node\":%u,\"boot\":%lu,\"produced\":%lu,"
      "\"model\":\"%s\",\"nonce\":%lu,\"activated\":%s,\"activation_seq\":%lu,\"seq\":%lu,\"timestamp_us\":%lu,\"state\":%u,"
      "\"reference\":[%.9g,%.9g,%.9g,%.9g],\"thresholds\":[%.9g,%.9g,%.9g,%.9g],"
      "\"settings\":[%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%lu,%lu],"
      "\"candidates\":%lu,\"cancelled\":%lu,\"starts\":%lu,\"ends\":%lu,\"interruptions\":%lu,\"max_compute_us\":%lu}",
      node,(unsigned long)boot,(unsigned long)produced,SHADOW_MODEL,(unsigned long)nonce,activated?"true":"false",
      (unsigned long)activationSeq,(unsigned long)seq,(unsigned long)timestamp,unsigned(state),
      reference.gyroB,reference.gyroS,reference.accelB,reference.accelS,
      thresholds.gyroStart,thresholds.accelStart,thresholds.gyroStop,thresholds.accelStop,
      SHADOW_START_GYRO_FLOOR_DPS,SHADOW_START_ACCEL_FLOOR_G,SHADOW_STOP_GYRO_FLOOR_DPS,SHADOW_STOP_ACCEL_FLOOR_G,
      SHADOW_START_K,SHADOW_STOP_K,(unsigned long)SHADOW_CONFIRM_US,(unsigned long)SHADOW_QUIET_US,
      (unsigned long)candidates,(unsigned long)cancelled,(unsigned long)starts,(unsigned long)ends,
      (unsigned long)interruptions,(unsigned long)maxComputeUs);
  }
  ShadowState state=ShadowState::Disarmed;
  ShadowReference reference;
  ShadowThresholds thresholds;
  uint32_t nonce=0,activationSeq=0,seq=0,timestamp=0,candidates=0,cancelled=0,starts=0,ends=0,interruptions=0,maxComputeUs=0;
  bool activated=false;
private:
  uint32_t candidateUs=0,quietUs=0,previousSeq=0,previousTime=0;
  bool havePrevious=false;
};
