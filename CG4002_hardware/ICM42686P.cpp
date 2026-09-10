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

  if (readRegister(REG_WHO_AM_I) != EXPECTED_WHO_AM_I) {
    return false;
  }

  if (!writeRegister(REG_PWR_MGMT0,
                     (LOW_NOISE_MODE << 2) | LOW_NOISE_MODE)) {
    return false;
  }

  if (!writeRegister(REG_GYRO_CONFIG0,
                     (DEFAULT_GYRO_FS << 5) | ODR_200HZ)) {
    return false;
  }

  if (!writeRegister(REG_ACCEL_CONFIG0,
                     (DEFAULT_ACCEL_FS << 5) | ODR_200HZ)) {
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
  return bus->endTransmission() == 0;
}

bool ICM42686P::readRegisters(uint8_t startAddress, uint8_t* data, size_t length) {
  if (bus == nullptr || data == nullptr || length == 0) {
    return false;
  }

  bus->beginTransmission(deviceAddress);
  bus->write(startAddress);
  if (bus->endTransmission(false) != 0) {
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
  uint8_t data[14];

  if (!readRegisters(REG_ACCEL_DATA_X1, data, sizeof(data))) {
    return false;
  }

  frame.timestamp_us = micros();
  frame.ax = (int16_t)((data[0] << 8) | data[1]);
  frame.ay = (int16_t)((data[2] << 8) | data[3]);
  frame.az = (int16_t)((data[4] << 8) | data[5]);
  frame.gx = (int16_t)((data[8] << 8) | data[9]);
  frame.gy = (int16_t)((data[10] << 8) | data[11]);
  frame.gz = (int16_t)((data[12] << 8) | data[13]);

  frame.ax_g = frame.ax / ACCEL_LSB_PER_G;
  frame.ay_g = frame.ay / ACCEL_LSB_PER_G;
  frame.az_g = frame.az / ACCEL_LSB_PER_G;
  frame.gx_dps = frame.gx / GYRO_LSB_PER_DPS;
  frame.gy_dps = frame.gy / GYRO_LSB_PER_DPS;
  frame.gz_dps = frame.gz / GYRO_LSB_PER_DPS;
  frame.status_flags = SENSOR_STATUS_PHYSICAL_UNITS_VALID;

  return true;
}
