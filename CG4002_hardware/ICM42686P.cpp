#include "ICM42686P.h"

namespace {
const uint8_t REG_PWR_MGMT0 = 0x4E;
const uint8_t REG_GYRO_CONFIG0 = 0x4F;
const uint8_t REG_ACCEL_CONFIG0 = 0x50;
const uint8_t REG_ACCEL_DATA_X1 = 0x1F;
const uint8_t REG_WHO_AM_I = 0x75;

}

ICM42686P::ICM42686P()
    : bus(nullptr), deviceAddress(DEFAULT_ADDRESS) {
}

bool ICM42686P::begin(TwoWire& wire, uint8_t address) {
  bus = &wire;
  deviceAddress = address;

  readback = ImuRegisterReadback();
  // Select bank zero explicitly, including after an ESP32-only reset.
  if (!writeRegister(0x76, 0x00) ||
      !readRegisters(REG_WHO_AM_I, &readback.whoAmI, 1)) {
    Serial.println("[imu] WHO_AM_I check failed");
    return false;
  }
  if (readback.whoAmI != EXPECTED_WHO_AM_I) {
    ioError = {"identity_mismatch", REG_WHO_AM_I, 0, 0, 0};
    Serial.printf("[imu] WHO_AM_I mismatch expected=0x%02X actual=0x%02X\n",
                  EXPECTED_WHO_AM_I, readback.whoAmI);
    return false;
  }

  if (!writeRegister(REG_PWR_MGMT0, 0x00)) {
    Serial.println("[imu] PWR_MGMT0 write failed");
    return false;
  }

  // Allow an already-running gyro to turn off before reconfiguration.
  delay(50);
  if (!writeRegister(REG_GYRO_CONFIG0, ImuConfig::GYRO_CONFIG0)) {
    Serial.println("[imu] GYRO_CONFIG0 write failed");
    return false;
  }

  if (!writeRegister(REG_ACCEL_CONFIG0, ImuConfig::ACCEL_CONFIG0)) {
    Serial.println("[imu] ACCEL_CONFIG0 write failed");
    return false;
  }

  if (!writeRegister(REG_PWR_MGMT0, ImuConfig::PWR_MGMT0)) {
    return false;
  }
  // No register access immediately after enabling; also allow gyro startup.
  delay(50);
  if (!readRegisters(REG_GYRO_CONFIG0, &readback.gyroConfig0, 1) ||
      !readRegisters(REG_ACCEL_CONFIG0, &readback.accelConfig0, 1) ||
      !readRegisters(REG_PWR_MGMT0, &readback.pwrMgmt0, 1)) {
    Serial.println("[imu] configuration readback failed");
    return false;
  }
  readback.verified = readback.gyroConfig0 == ImuConfig::GYRO_CONFIG0 &&
      readback.accelConfig0 == ImuConfig::ACCEL_CONFIG0 &&
      (readback.pwrMgmt0 & 0x0F) == ImuConfig::PWR_MGMT0;
  if (!readback.verified) ioError = {"config_mismatch", REG_GYRO_CONFIG0, 0, 0, 0};
  Serial.printf("[imu] WHO_AM_I=0x%02X GYRO_CONFIG0=0x%02X ACCEL_CONFIG0=0x%02X PWR_MGMT0=0x%02X verified=%u\n",
                readback.whoAmI, readback.gyroConfig0, readback.accelConfig0,
                readback.pwrMgmt0, readback.verified);
  return readback.verified;
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
    ioError = {"not_initialized", address, 0, 2, 0};
    return false;
  }

  bus->beginTransmission(deviceAddress);
  bus->write(address);
  bus->write(value);
  uint8_t error = bus->endTransmission();
  if (error) ioError = {"write", address, error, 2, 0};
  return error == 0;
}

bool ICM42686P::readRegisters(uint8_t startAddress, uint8_t* data, size_t length) {
  if (bus == nullptr || data == nullptr || length == 0) {
    ioError = {"invalid_read", startAddress, 0, length, 0};
    return false;
  }

  bus->beginTransmission(deviceAddress);
  bus->write(startAddress);
  uint8_t writeError = bus->endTransmission(false);  // I2C repeated START
  if (writeError != 0) {
    ioError = {"read_address", startAddress, writeError, length, 0};
    return false;
  }

  size_t received = bus->requestFrom(deviceAddress, length);
  if (received != length) {
    ioError = {"read_data", startAddress, 0, length, received};
    while (bus->available()) bus->read();
    return false;
  }

  for (size_t i = 0; i < length; i++) {
    int value = bus->read();
    if (value < 0) {
      ioError = {"read_buffer", startAddress, 0, length, i};
      return false;
    }
    data[i] = static_cast<uint8_t>(value);
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

  frame.ax_g = frame.ax / ImuConfig::ACCEL_LSB_PER_G;
  frame.ay_g = frame.ay / ImuConfig::ACCEL_LSB_PER_G;
  frame.az_g = frame.az / ImuConfig::ACCEL_LSB_PER_G;
  frame.gx_dps = frame.gx / ImuConfig::GYRO_LSB_PER_DPS;
  frame.gy_dps = frame.gy / ImuConfig::GYRO_LSB_PER_DPS;
  frame.gz_dps = frame.gz / ImuConfig::GYRO_LSB_PER_DPS;
  frame.status_flags = SENSOR_STATUS_PHYSICAL_UNITS_VALID;

  return true;
}
