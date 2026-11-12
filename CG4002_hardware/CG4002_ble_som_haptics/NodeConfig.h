#pragma once
#include <stdint.h>

// Select ONE role here before each upload. Both boards use the same sketch.
// Compiler overrides are used only to build/test both variants reproducibly.
#define SOM_FOREARM 1
#define SOM_PADDLE 2
#ifndef SOM_NODE_ROLE
#define SOM_NODE_ROLE SOM_FOREARM
#endif

// BLE migration: each board detects locally; the existing central combines
// arriving streams. No inter-node joint-energy calculation runs on either board.
#ifndef SOM_COORDINATED_CAPTURE
#define SOM_COORDINATED_CAPTURE 0
#endif
// LocalMotion owns motion-based BLE output; no continuous Wi-Fi reference.
#ifndef SOM_CONTINUOUS_CAPTURE
#define SOM_CONTINUOUS_CAPTURE 0
#endif

namespace NodeConfig {
constexpr bool COORDINATED_CAPTURE = SOM_COORDINATED_CAPTURE != 0;
struct Profile {
  uint8_t id;
  const char* role;
  const char* axes;
  bool accelVerified;
  const char* calibrationId;
  float offset[3];
  float scale[3];
  float startGyro, startAccel, stopGyro, stopAccel, startK, stopK;
  uint32_t confirmUs, quietUs;
};

// This calibration belongs only to the already-tested physical forearm sensor.
constexpr Profile FOREARM = {
  1, "FOREARM", "sensor_native_provisional", true, "cp1c_20261015_121254",
  {0.0239328207f,-0.0011241512f,0.0114859327f},
  {0.9942584024f,0.9958358067f,0.9928539721f},
  30.0f,0.08f,12.0f,0.04f,6.0f,3.0f,30000,150000
};

// PADDLE-only fit: paddle_calibration_20261026_232012_586114 (LiPo).
// Reviewed with the user's accepted z_minus gyro-stillness exception. Both
// independent tilt validations pass. Actual flashed behavior awaits JCP1b;
// this flag identifies the reviewed stored coefficients, not a completed release.
// Axes: +X right, +Y handle base toward face tip, +Z outward normal from the
// instrumented paddle face. Sensor axes must physically match; mapping is identity.
constexpr Profile PADDLE = {
  2, "PADDLE", "x_right_y_tip_z_face_out", true, "paddle_jcp1_20261026_232012",
  {-0.0018233730f,-0.0002208856f,0.0147838995f},
  {0.9932892511f,0.9957681891f,0.9894305780f},
  30.0f,0.08f,12.0f,0.04f,6.0f,3.0f,30000,150000
};

static_assert(SOM_NODE_ROLE==SOM_FOREARM || SOM_NODE_ROLE==SOM_PADDLE,"Select FOREARM or PADDLE");
constexpr Profile ACTIVE = SOM_NODE_ROLE==SOM_FOREARM ? FOREARM : PADDLE;
constexpr bool ACCEL_VERIFIED=ACTIVE.accelVerified;
static_assert(ACTIVE.scale[0]>.8f && ACTIVE.scale[0]<1.2f &&
              ACTIVE.scale[1]>.8f && ACTIVE.scale[1]<1.2f &&
              ACTIVE.scale[2]>.8f && ACTIVE.scale[2]<1.2f,"Invalid acceleration scales");
}
