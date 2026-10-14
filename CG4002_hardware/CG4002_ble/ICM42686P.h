#ifndef ICM42686P_H
#define ICM42686P_H

#include <Arduino.h>
#include <Wire.h>
#include "SensorFrame.h"
#include "ImuConfig.h"

struct ImuRegisterReadback {
  uint8_t whoAmI = 0;
  uint8_t gyroConfig0 = 0;
  uint8_t accelConfig0 = 0;
  uint8_t pwrMgmt0 = 0;
  bool verified = false;
};

// Last failed transaction is retained across successful reads for diagnosis.
// Wire does not expose the underlying ESP-IDF error for requestFrom().
struct ImuIoError {
  const char* stage = "none";
  uint8_t reg = 0;
  uint8_t wireStatus = 0;
  size_t expected = 0;
  size_t received = 0;
};

class ICM42686P {

public:
  static const uint8_t DEFAULT_ADDRESS = 0x68;
  static const uint8_t EXPECTED_WHO_AM_I = 0x44;

  ICM42686P();

  bool begin(TwoWire& wire, uint8_t address = DEFAULT_ADDRESS);
  bool readRaw(SensorFrame& frame);
  const ImuRegisterReadback& configuration() const { return readback; }
  const ImuIoError& lastError() const { return ioError; }

  uint8_t readRegister(uint8_t address);
  bool writeRegister(uint8_t address, uint8_t value);

private:
  TwoWire* bus;
  uint8_t deviceAddress;
  ImuRegisterReadback readback;
  ImuIoError ioError;

  bool readRegisters(uint8_t startAddress, uint8_t* data, size_t length);
};

#endif
