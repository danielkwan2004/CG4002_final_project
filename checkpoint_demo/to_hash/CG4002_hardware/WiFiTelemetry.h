#ifndef WIFI_TELEMETRY_H
#define WIFI_TELEMETRY_H

#include <Arduino.h>
#include <WiFi.h>
#include "SensorFrame.h"
#include "TxQueue.h"

class CaptureDiagnostics;

// Socket-call counters include retry attempts, NOT final sample losses.
struct UdpDiagnostics {
  uint32_t attempted = 0, accepted = 0, failed = 0;
  uint32_t dataFailed = 0, controlFailed = 0;
  uint32_t stages[4] = {};  // format, not-ready, sendto error, short send
  uint32_t errors[4] = {};  // ENOMEM, EAGAIN/ENOBUFS, network, other
  uint32_t report = 0;
  int lastErrno = 0, lastStage = 0, lastSent = 0, lastWifi = 0;
  bool lastData = false;
  uint32_t lastMs = 0, lastBytes = 0, lastHeap = 0, lastRssiAgeMs = 0;
  int lastRssi = 0;
};

class WiFiTelemetry {

public:
  bool begin(const char* ssid, const char* password, const char* laptopIp,
             uint16_t port);
  bool sendFrame(const SensorFrame& frame, uint32_t bootId, uint32_t burstId,
                 uint32_t burstIndex);
  bool enqueueFrame(const SensorFrame& frame, uint32_t bootId, uint32_t burstId,
                    uint32_t burstIndex);
  void service(CaptureDiagnostics& capture);
  void closeBurst(uint32_t burst) { queue.closeBurst(burst); }
  void cancelThrough(uint32_t burst, CaptureDiagnostics& capture);
  int formatQueueDiagnostics(char* packet, size_t capacity, uint8_t node,
                             uint32_t boot, uint32_t produced);
  bool sendPacket(const char* packet, size_t length);
  int formatDiagnostics(char* packet, size_t capacity, uint8_t node,
                        uint32_t boot, uint32_t produced);
  IPAddress localIP() const;

private:
  bool transmit(const char* packet, size_t length, bool data);
  bool recordFailure(int stage, int error, size_t length, int sent, bool data);
  bool openSocket(uint16_t port);
  void refreshLinkMetrics();
  int socketFd = -1;
  IPAddress laptopAddress;
  uint16_t destinationPort = 0;
  UdpDiagnostics diagnostics;
  TxQueue queue;
  uint32_t queueReport = 0;
  int cachedRssi = 0;
  uint32_t rssiSampleMs = 0;
  bool eventRegistered = false;
  portMUX_TYPE eventMux = portMUX_INITIALIZER_UNLOCKED;
  uint32_t disconnects = 0, lastDisconnectMs = 0;
  uint16_t lastDisconnectReason = 0;
};

#endif
