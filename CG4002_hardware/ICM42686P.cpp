#include "ICM42686P.h"

namespace {
const uint8_t REG_PWR_MGMT0 = 0x4E;
const uint8_t REG_GYRO_CONFIG0 = 0x4F;
const uint8_t REG_ACCEL_CONFIG0 = 0x50;
const uint8_t REG_ACCEL_DATA_X1 = 0x1F;
const uint8_t REG_WHO_AM_I = 0x75;

const uint8_t LOW_NOISE_MODE = 0x03;
const uint8_t ODR_200HZ = 0x07;
const uint8_t DEFAULT_GYRO_FS = 0x00;   // +/-2000 dps
const uint8_t DEFAULT_ACCEL_FS = 0x01;  // +/-16 g
const float ACCEL_LSB_PER_G = 2048.0f;
const float GYRO_LSB_PER_DPS = 16.4f;
}

ICM42686P::ICM42686P()
    : bus(nullptr), deviceAddress(DEFAULT_ADDRESS) {
}

bool ICM42686P::begin(TwoWire& wire, uint8_t address) {
  bus = &wire;
  deviceAddress = address;

  uint8_t whoAmI = readRegister(REG_WHO_AM_I);
  if (whoAmI != EXPECTED_WHO_AM_I) {
    Serial.println("[imu] WHO_AM_I check failed");
    return false;
  }

  if (!writeRegister(REG_PWR_MGMT0,
                     (LOW_NOISE_MODE << 2) | LOW_NOISE_MODE)) {
    Serial.println("[imu] PWR_MGMT0 write failed");
    return false;
  }

  if (!writeRegister(REG_GYRO_CONFIG0,
                     (DEFAULT_GYRO_FS << 5) | ODR_200HZ)) {
    Serial.println("[imu] GYRO_CONFIG0 write failed");
    return false;
  }

  if (!writeRegister(REG_ACCEL_CONFIG0,
                     (DEFAULT_ACCEL_FS << 5) | ODR_200HZ)) {
    Serial.println("[imu] ACCEL_CONFIG0 write failed");
    return false;
  }

  delay(50);
  return true;
}

uint8_t ICM42686P::readRegister(uint8_t address) {
  uint8_t value = 0;

  if (!readRegisters(address, &value, 1)) {
    return 0;
  }

  return value;
}

bool ICM42686P::writeRegister(uint8_t address, uint8_t value) {
  if (bus == nullptr) {
    return false;
  }

  bus->beginTransmission(deviceAddress);
  bus->write(address);
  bus->write(value);
  uint8_t error = bus->endTransmission();
  return error == 0;
}

bool ICM42686P::readRegisters(uint8_t startAddress, uint8_t* data, size_t length) {
  if (bus == nullptr || data == nullptr || length == 0) {
    return false;
  }

  bus->beginTransmission(deviceAddress);
  bus->write(startAddress);
  uint8_t writeError = bus->endTransmission(true);
  if (writeError != 0) {
    return false;
  }

  size_t received = bus->requestFrom(deviceAddress, length);
  if (received != length) {
    return false;
  }

  for (size_t i = 0; i < length; i++) {
    data[i] = bus->read();
  }

  return true;
}

bool ICM42686P::readRaw(SensorFrame& frame) {
  // Accel X/Y/Z = 0x1F-0x24, Gyro X/Y/Z = 0x25-0x2A -- 12 bytes total.
  // (0x2B/0x2C beyond this are TMST_FSYNCH/L, not gyro data -- do not read them.)
  uint8_t data[12];

  if (!readRegisters(REG_ACCEL_DATA_X1, data, sizeof(data))) {
    return false;
  }

  frame.timestamp_us = micros();
  frame.ax = (int16_t)((data[0] << 8) | data[1]);
  frame.ay = (int16_t)((data[2] << 8) | data[3]);
  frame.az = (int16_t)((data[4] << 8) | data[5]);
  frame.gx = (int16_t)((data[6] << 8) | data[7]);
  frame.gy = (int16_t)((data[8] << 8) | data[9]);
  frame.gz = (int16_t)((data[10] << 8) | data[11]);

  frame.ax_g = frame.ax / ACCEL_LSB_PER_G;
  frame.ay_g = frame.ay / ACCEL_LSB_PER_G;
  frame.az_g = frame.az / ACCEL_LSB_PER_G;
  frame.gx_dps = frame.gx / GYRO_LSB_PER_DPS;
  frame.gy_dps = frame.gy / GYRO_LSB_PER_DPS;
  frame.gz_dps = frame.gz / GYRO_LSB_PER_DPS;
  frame.status_flags = SENSOR_STATUS_PHYSICAL_UNITS_VALID;

  return true;
}
