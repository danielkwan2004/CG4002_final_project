#ifndef WIFI_TELEMETRY_H
#define WIFI_TELEMETRY_H

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include "SensorFrame.h"

class WiFiTelemetry {

public:
  bool begin(const char* ssid, const char* password, const char* laptopIp,
             uint16_t port);
  bool sendFrame(const SensorFrame& frame);
  IPAddress localIP() const;

private:
  WiFiUDP udp;
  IPAddress laptopAddress;
  uint16_t destinationPort = 0;
};

#endif
