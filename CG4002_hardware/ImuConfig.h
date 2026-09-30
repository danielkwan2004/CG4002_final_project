#ifndef IMU_CONFIG_H
#define IMU_CONFIG_H

#include <Arduino.h>

// ICM-42686-P range encoding (not interchangeable with other ICM models).
// DS-000639, sections 3.1/3.2 and 14.37/14.38.
namespace ImuConfig {
constexpr uint8_t GYRO_CONFIG0 = 0x27;   // FS_SEL=1: +/-2000 dps; ODR=7: 200 Hz
constexpr uint8_t ACCEL_CONFIG0 = 0x27;  // FS_SEL=1: +/-16 g; ODR=7: 200 Hz
constexpr uint8_t PWR_MGMT0 = 0x0F;     // Both sensors in low-noise mode
constexpr float GYRO_LSB_PER_DPS = 16.4f;
constexpr float ACCEL_LSB_PER_G = 2048.0f;
constexpr unsigned long SAMPLE_PERIOD_US = 5000;
}

#endif
