#include <Wire.h>

// ICM-42686-P acquisition for BLE.ino; this sketch no longer uses Wi-Fi.
constexpr int SDA_PIN = 21;
constexpr int SCL_PIN = 22;
constexpr uint32_t IMU_POLL_US = 2000;  // Check data-ready every 2 ms.
constexpr uint32_t RETRY_MS = 5000;

// ICM-42686-P bank 0 registers. The sensor is set to 200 Hz, +/-16 g,
// +/-2000 degrees/s. No external IMU library is needed.
constexpr uint8_t WHO_AM_I = 0x75;
constexpr uint8_t REG_BANK_SEL = 0x76;
constexpr uint8_t PWR_MGMT0 = 0x4E; 
constexpr uint8_t GYRO_CONFIG0 = 0x4F;
constexpr uint8_t ACCEL_CONFIG0 = 0x50;
constexpr uint8_t INT_SOURCE0 = 0x65;
constexpr uint8_t INT_STATUS = 0x2D;
constexpr uint8_t ACCEL_DATA_X1 = 0x1F;
constexpr uint8_t EXPECTED_ID = 0x44;

uint8_t imuAddress = 0;
bool imuReady = false;
const char *imuState = "starting";
int16_t latest[6] = {};
uint32_t freshSamples = 0;
uint32_t readErrors = 0;
uint32_t nextPollUs = 0;
uint32_t lastImuTryMs = 0;

bool writeRegister(uint8_t address, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool readRegisters(uint8_t address, uint8_t reg, uint8_t *data, uint8_t length) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0 ||
      Wire.requestFrom(address, length, static_cast<uint8_t>(true)) != length) {
    return false;
  }
  for (uint8_t i = 0; i < length; ++i) {
    data[i] = Wire.read();
  }
  return true;
}

bool startImu() {
  imuReady = false;
  imuAddress = 0;
  imuState = "not_found";
  uint8_t id = 0;

  for (uint8_t address = 0x68; address <= 0x69; ++address) {
    if (writeRegister(address, REG_BANK_SEL, 0x00) &&
        readRegisters(address, WHO_AM_I, &id, 1)) {
      if (id == EXPECTED_ID) {
        imuAddress = address;
        break;
      }
      imuState = "wrong_id";
    }
  }
  if (imuAddress == 0) {
    return false;
  }

  if (!writeRegister(imuAddress, REG_BANK_SEL, 0x00) ||
      !writeRegister(imuAddress, GYRO_CONFIG0, 0x27) ||
      !writeRegister(imuAddress, ACCEL_CONFIG0, 0x27) ||
      !writeRegister(imuAddress, INT_SOURCE0, 0x08) ||
      !writeRegister(imuAddress, PWR_MGMT0, 0x0F)) {
    imuState = "config_error";
    imuAddress = 0;
    return false;
  }

  delay(50);  // Let the gyroscope start before reading samples.
  imuReady = true;
  imuState = "ok";
  nextPollUs = micros() + IMU_POLL_US;
  return true;
}

bool pollImu() {
  if (!imuReady || static_cast<int32_t>(micros() - nextPollUs) < 0) {
    return false;
  }
  nextPollUs = micros() + IMU_POLL_US;

  uint8_t status = 0;
  if (!readRegisters(imuAddress, INT_STATUS, &status, 1)) {
    imuReady = false;
    imuState = "read_error";
    ++readErrors;
    return false;
  }
  if ((status & 0x08) == 0) {
    return false;  // No new 200 Hz sample yet.
  }

  uint8_t raw[12];
  if (!readRegisters(imuAddress, ACCEL_DATA_X1, raw, sizeof(raw))) {
    imuReady = false;
    imuState = "read_error";
    ++readErrors;
    return false;
  }
  for (uint8_t axis = 0; axis < 6; ++axis) {
    latest[axis] = static_cast<int16_t>(
        (static_cast<uint16_t>(raw[axis * 2]) << 8) | raw[axis * 2 + 1]);
  }
  ++freshSamples;
  return true;
}

