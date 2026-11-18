#pragma once
#include <stdint.h>
#include "NodeConfig.h"

// Shared two-node increment: role and per-node thresholds are in NodeConfig.h.
// Shared motion/capture constants live here; per-node settings are in NodeConfig.h.
// Reference collection is always continuous until the first detector activation.
#ifndef SOM_CONTINUOUS_CAPTURE
#define SOM_CONTINUOUS_CAPTURE 1
#endif
namespace MotionGateConfig {
constexpr bool CONTINUOUS_CAPTURE = NodeConfig::COORDINATED_CAPTURE || SOM_CONTINUOUS_CAPTURE != 0 || !NodeConfig::ACCEL_VERIFIED;
#ifdef SOM_LEGACY_TEST
constexpr bool SELECTIVE_CAPTURE = false;
#else
constexpr bool SELECTIVE_CAPTURE = !CONTINUOUS_CAPTURE;
#endif
constexpr float FILTER_ALPHA = 0.2f;
constexpr float GYRO_START_DPS = 40.0f;
constexpr float GYRO_STOP_DPS = 15.0f;
constexpr float ACCEL_START_G = 0.30f;
constexpr float ACCEL_STOP_G = 0.15f;
constexpr unsigned long END_QUIET_MS = 150;
// Continuous capture uses fixed transport chunks, not detected-motion bursts.
constexpr unsigned long CAPTURE_CHUNK_MS = 5000;
constexpr const char* CHECKPOINT = "som_two_node";
// Same CP4a/CP4b range rules; this increment observes them in continuous mode.
constexpr const char* SEGMENT_MODEL = "history60_v1";
constexpr uint32_t SEGMENT_HISTORY_US = 300000;
constexpr unsigned SEGMENT_HISTORY_SAMPLES = 60;
constexpr unsigned SEGMENT_REPORT_HISTORY = 8;
static_assert(SEGMENT_HISTORY_SAMPLES >= 1 && SEGMENT_HISTORY_SAMPLES <= 100, "bounded history");
static_assert(SEGMENT_REPORT_HISTORY >= 2 && SEGMENT_REPORT_HISTORY <= 16, "bounded reports");
constexpr const char* SHADOW_MODEL = "som_shadow_v1";
constexpr float SHADOW_START_GYRO_FLOOR_DPS = NodeConfig::ACTIVE.startGyro;
constexpr float SHADOW_START_ACCEL_FLOOR_G = NodeConfig::ACTIVE.startAccel;
constexpr float SHADOW_STOP_GYRO_FLOOR_DPS = NodeConfig::ACTIVE.stopGyro;
constexpr float SHADOW_STOP_ACCEL_FLOOR_G = NodeConfig::ACTIVE.stopAccel;
constexpr float SHADOW_START_K = NodeConfig::ACTIVE.startK;
constexpr float SHADOW_STOP_K = NodeConfig::ACTIVE.stopK;
constexpr uint32_t SHADOW_CONFIRM_US = NodeConfig::ACTIVE.confirmUs;
constexpr uint32_t SHADOW_QUIET_US = NodeConfig::ACTIVE.quietUs;
static_assert(SHADOW_START_K > SHADOW_STOP_K && SHADOW_STOP_K >= 0, "shadow multipliers");
static_assert(SHADOW_START_GYRO_FLOOR_DPS > SHADOW_STOP_GYRO_FLOOR_DPS &&
              SHADOW_START_ACCEL_FLOOR_G > SHADOW_STOP_ACCEL_FLOOR_G, "shadow floors");
// Features used by the start/stop detector in both selective and reference mode.
constexpr const char* FEATURE_MODEL = "rms10_v1";
constexpr unsigned FEATURE_WINDOW_SAMPLES = 10; // 50 ms at 200 Hz; endpoints span 45 ms
constexpr unsigned FEATURE_MIN_DT_US = 2500;
constexpr unsigned FEATURE_MAX_DT_US = 7500; // a missing 5 ms sample invalidates the window
constexpr unsigned BASELINE_TRIM_MS = 1000; // each edge of the prompted 12 s reference
constexpr unsigned BASELINE_MIN_SAMPLES = 1900; // >=95% of nominal 10 s interior
constexpr unsigned BASELINE_MAX_SAMPLES = 2400;
constexpr unsigned BASELINE_MIN_SPAN_US = 9500000;
constexpr float BASELINE_GYRO_SPREAD_FLOOR_DPS = 0.5f;
constexpr float BASELINE_ACCEL_SPREAD_FLOOR_G = 0.005f;
static_assert(FEATURE_WINDOW_SAMPLES >= 2 && FEATURE_WINDOW_SAMPLES <= 40, "feature window bound");
static_assert(GYRO_START_DPS > GYRO_STOP_DPS && GYRO_STOP_DPS >= 0, "gyro hysteresis");
static_assert(ACCEL_START_G > ACCEL_STOP_G && ACCEL_STOP_G >= 0, "accel hysteresis");
static_assert(FILTER_ALPHA > 0 && FILTER_ALPHA <= 1, "LPF alpha");
static_assert(CAPTURE_CHUNK_MS >= 1000 && CAPTURE_CHUNK_MS <= 30000, "capture chunk range");
}
