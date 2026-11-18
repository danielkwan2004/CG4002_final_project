#pragma once
#include "NodeConfig.h"
// Corrected g = (raw g - per-sensor offset) / per-sensor scale, before the LPF.
namespace AccelCalibrationConfig {
constexpr bool VERIFIED = NodeConfig::ACCEL_VERIFIED;
constexpr const char* METHOD = VERIFIED ? "six_pose_fixed_v1" : "identity_pending_v1";
constexpr const char* ID = NodeConfig::ACTIVE.calibrationId;
static constexpr const float (&OFFSET_G)[3] = NodeConfig::ACTIVE.offset;
static constexpr const float (&SCALE)[3] = NodeConfig::ACTIVE.scale;
}
