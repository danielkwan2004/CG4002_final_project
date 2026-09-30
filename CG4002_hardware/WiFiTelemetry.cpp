#include "WiFiTelemetry.h"
#include "CaptureDiagnostics.h"
#include "SampleEncoding.h"
#include <lwip/sockets.h>
#include <errno.h>

namespace {
const char* wifiStatusName(wl_status_t status) {
  switch (status) {
    case WL_IDLE_STATUS: return "IDLE";
    case WL_NO_SSID_AVAIL: return "NO_SSID";
    case WL_SCAN_COMPLETED: return "SCAN_COMPLETED";
    case WL_CONNECTED: return "CONNECTED";
    case WL_CONNECT_FAILED: return "CONNECT_FAILED";
    case WL_CONNECTION_LOST: return "CONNECTION_LOST";
    case WL_DISCONNECTED: return "DISCONNECTED";
    default: return "UNKNOWN";
  }
}
}

bool WiFiTelemetry::begin(const char* ssid, const char* password,
                          const char* laptopIp, uint16_t port) {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true);
  delay(250);

  if (!laptopAddress.fromString(laptopIp)) {
    Serial.println("[wifi] invalid laptop IP");
    return false;
  }

  Serial.print("[wifi] scanning for SSID: ");
  Serial.println(ssid);
  int networkCount = WiFi.scanNetworks();
  bool ssidVisible = false;
  for (int network = 0; network < networkCount; network++) {
    Serial.print("[wifi] found SSID=");
    Serial.print(WiFi.SSID(network));
    Serial.print(" channel=");
    Serial.print(WiFi.channel(network));
    Serial.print(" RSSI=");
    Serial.println(WiFi.RSSI(network));

    if (WiFi.SSID(network) == ssid) {
      ssidVisible = true;
    }
  }
  WiFi.scanDelete();

  if (!ssidVisible) {
    Serial.println("[wifi] SSID not visible");
  }

  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);
  if (!eventRegistered) {
    // The callback runs on Arduino's network event task, not the sampling task.
    WiFi.onEvent([this](WiFiEvent_t, WiFiEventInfo_t info) {
      const uint32_t now = millis();
      portENTER_CRITICAL(&eventMux);
      ++disconnects;
      lastDisconnectReason = info.wifi_sta_disconnected.reason;
      lastDisconnectMs = now;
      portEXIT_CRITICAL(&eventMux);
    }, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
    eventRegistered = true;
  }
  WiFi.begin(ssid, password);
  unsigned long startTime = millis();
  unsigned long nextStatusPrint = startTime;
  while (WiFi.status() != WL_CONNECTED && millis() - startTime < 30000) {
    if (millis() >= nextStatusPrint) {
      Serial.print("[wifi] waiting, status=");
      Serial.print(wifiStatusName(WiFi.status()));
      Serial.print(" (");
      Serial.print(static_cast<int>(WiFi.status()));
      Serial.println(")");
      nextStatusPrint += 1000;
    }
    delay(100);
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.print("[wifi] connect failed, final status=");
    Serial.print(wifiStatusName(WiFi.status()));
    Serial.print(" (");
    Serial.print(static_cast<int>(WiFi.status()));
    Serial.println(")");
    return false;
  }

  // Favor repeatable bench latency over radio power saving. Battery runtime
  // must be measured with this setting; it is not a low-power configuration.
  WiFi.setSleep(false);

  destinationPort = port;
  refreshLinkMetrics();
  return openSocket(port);
}

bool WiFiTelemetry::openSocket(uint16_t port) {
  if (socketFd >= 0) close(socketFd);
  socketFd = socket(AF_INET, SOCK_DGRAM, 0);
  int error = errno;
  if (socketFd >= 0) {
    sockaddr_in local = {};
    local.sin_family = AF_INET;
    local.sin_port = htons(port);
    local.sin_addr.s_addr = INADDR_ANY;
    int yes = 1;
    if (setsockopt(socketFd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes)) == 0 &&
        bind(socketFd, reinterpret_cast<sockaddr*>(&local), sizeof(local)) == 0 &&
        fcntl(socketFd, F_SETFL, O_NONBLOCK) == 0) return true;
    error = errno;
    close(socketFd);
    socketFd = -1;
  }
  Serial.printf("[wifi] socket setup failed errno=%d\n", error);
  return false;
}

void WiFiTelemetry::refreshLinkMetrics() {
  cachedRssi = WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0;
  rssiSampleMs = millis();
}

IPAddress WiFiTelemetry::localIP() const {
  return WiFi.localIP();
}

bool WiFiTelemetry::sendFrame(const SensorFrame& frame, uint32_t bootId,
                              uint32_t burstId, uint32_t burstIndex) {
  char packet[480];
  QueuedSample item = {frame, bootId, burstId, burstIndex, millis()};
  int length = encodeSample(item, packet, sizeof(packet));

  if (length <= 0 || length >= static_cast<int>(sizeof(packet))) {
    ++diagnostics.attempted;
    return recordFailure(1, EMSGSIZE, length > 0 ? length : 0, 0, true);
  }

  return transmit(packet, static_cast<size_t>(length), true);
}

bool WiFiTelemetry::enqueueFrame(const SensorFrame& frame, uint32_t boot,
                                uint32_t burst, uint32_t index) {
  return queue.enqueue(frame, boot, burst, index, millis());
}

void WiFiTelemetry::service(CaptureDiagnostics& capture) {
  queue.service(millis(), encodeSample,
      [this](const char* packet, size_t length) {
        if (transmit(packet, length, true)) return TxResult::Accepted;
        const int e = diagnostics.lastErrno;
        const bool transient = e == ENOMEM || e == EAGAIN || e == EWOULDBLOCK ||
            e == ENOBUFS || e == ENETDOWN || e == ENETUNREACH ||
            e == EHOSTUNREACH || e == ENOTCONN || e == ETIMEDOUT;
        return transient ? TxResult::Retry : TxResult::PermanentFailure;
      },
      [&capture](uint32_t burst, uint32_t n, bool accepted) {
        capture.recordDelivery(burst, n, accepted);
      });
}

void WiFiTelemetry::cancelThrough(uint32_t burst, CaptureDiagnostics& capture) {
  queue.cancelThrough(burst, [&capture](uint32_t id, uint32_t n, bool accepted) {
    capture.recordDelivery(id, n, accepted);
  });
}

int WiFiTelemetry::formatQueueDiagnostics(char* packet, size_t capacity,
    uint8_t node, uint32_t boot, uint32_t produced) {
  const TxQueueCounters& q = queue.counters();
  return snprintf(packet, capacity,
      "{\"v\":4,\"type\":\"txqueue\",\"node\":%u,\"boot\":%lu,\"produced\":%lu,"
      "\"report\":%lu,\"offered\":%lu,\"accepted\":%lu,\"dropped\":%lu,\"pending\":%u,"
      "\"recovered\":%lu,\"overflow\":%lu,\"expired\":%lu,\"permanent\":%lu,\"cancelled\":%lu,"
      "\"calls\":%lu,\"errors\":%lu,\"retries\":%lu,\"datagrams\":%lu,"
      "\"high_water\":%lu,\"max_age_ms\":%lu,\"oldest_ms\":%lu,"
      "\"capacity\":%u,\"batch_size\":%u,\"flush_ms\":%lu,\"max_age_limit_ms\":%lu,\"retry_ms\":%lu}",
      node, (unsigned long)boot, (unsigned long)produced, (unsigned long)++queueReport,
      (unsigned long)q.offered, (unsigned long)q.accepted, (unsigned long)q.dropped,
      (unsigned)queue.pending(), (unsigned long)q.recovered, (unsigned long)q.overflow,
      (unsigned long)q.expired, (unsigned long)q.permanent, (unsigned long)q.cancelled,
      (unsigned long)q.calls, (unsigned long)q.errors, (unsigned long)q.retries,
      (unsigned long)q.datagrams, (unsigned long)q.highWater, (unsigned long)q.maxAgeMs,
      (unsigned long)queue.oldestAgeMs(millis()), (unsigned)TxQueue::CAPACITY,
      (unsigned)TxQueue::BATCH_SIZE, (unsigned long)TxQueue::FLUSH_MS,
      (unsigned long)TxQueue::MAX_AGE_MS, (unsigned long)TxQueue::RETRY_MS);
}

bool WiFiTelemetry::sendPacket(const char* packet, size_t length) {
  return transmit(packet, length, false);
}

bool WiFiTelemetry::transmit(const char* packet, size_t length, bool data) {
  ++diagnostics.attempted;
  // Stay below NetworkUDP's previous datagram limit; never split an application
  // payload into untracked sends or emit a truncated diagnostic message.
  if (packet == nullptr || length == 0 || length > 1460) {
    return recordFailure(1, EMSGSIZE, length, 0, data);
  }
  if (socketFd < 0 || destinationPort == 0) {
    return recordFailure(2, ENOTCONN, length, -1, data);
  }
  sockaddr_in recipient = {};
  recipient.sin_family = AF_INET;
  recipient.sin_port = htons(destinationPort);
  recipient.sin_addr.s_addr = static_cast<uint32_t>(laptopAddress);

  // Same lwIP sendto primitive as Arduino NetworkUDP::endPacket(), but capture
  // errno BEFORE logging/API calls can overwrite it. Retries are scheduled by
  // the bounded queue, never by blocking/delaying this socket call.
  errno = 0;
  int sent = sendto(socketFd, packet, length, MSG_DONTWAIT,
                    reinterpret_cast<sockaddr*>(&recipient), sizeof(recipient));
  const int error = errno;
  if (sent < 0) return recordFailure(3, error, length, sent, data);
  if (static_cast<size_t>(sent) != length) {
    return recordFailure(4, EIO, length, sent, data);
  }
  ++diagnostics.accepted;
  return true;
}

bool WiFiTelemetry::recordFailure(int stage, int error, size_t length,
                                  int sent, bool data) {
  ++diagnostics.failed;
  if (data) ++diagnostics.dataFailed; else ++diagnostics.controlFailed;
  ++diagnostics.stages[stage - 1];
  const int category = error == ENOMEM ? 0 :
      (error == EAGAIN || error == EWOULDBLOCK || error == ENOBUFS) ? 1 :
      (error == ENETDOWN || error == ENETUNREACH || error == EHOSTUNREACH ||
       error == ENOTCONN) ? 2 : 3;
  ++diagnostics.errors[category];
  diagnostics.lastErrno = error;
  diagnostics.lastStage = stage;
  diagnostics.lastData = data;
  diagnostics.lastMs = millis();
  diagnostics.lastBytes = length;
  diagnostics.lastSent = sent;
  diagnostics.lastWifi = static_cast<int>(WiFi.status());
  // Cache RSSI once per report, not on every failed 200 Hz send. Its age makes
  // clear that this is not necessarily the signal strength at the failure.
  diagnostics.lastRssi = cachedRssi;
  diagnostics.lastRssiAgeMs = diagnostics.lastMs - rssiSampleMs;
  diagnostics.lastHeap = ESP.getFreeHeap();
  return false;
}

int WiFiTelemetry::formatDiagnostics(char* packet, size_t capacity, uint8_t node,
                                    uint32_t boot, uint32_t produced) {
  refreshLinkMetrics();
  uint32_t lostCount, lostMs;
  uint16_t reason;
  portENTER_CRITICAL(&eventMux);
  lostCount = disconnects;
  lostMs = lastDisconnectMs;
  reason = lastDisconnectReason;
  portEXIT_CRITICAL(&eventMux);
  const UdpDiagnostics& d = diagnostics;
  ++diagnostics.report;
  // Snapshot precedes its own send; a failed report is reflected next time.
  return snprintf(packet, capacity,
      "{\"v\":4,\"type\":\"transport\",\"node\":%u,\"boot\":%lu,\"produced\":%lu,"
      "\"report\":%lu,\"backend\":\"lwip_queued_v2\",\"time_ms\":%lu,"
      "\"attempted\":%lu,\"accepted\":%lu,\"failed\":%lu,\"data_failed\":%lu,\"control_failed\":%lu,"
      "\"stages\":[%lu,%lu,%lu,%lu],\"errors\":[%lu,%lu,%lu,%lu],"
      "\"last_errno\":%d,\"last_stage\":%d,\"last_data\":%s,\"last_ms\":%lu,"
      "\"last_bytes\":%lu,\"last_sent\":%d,\"last_wifi\":%d,\"last_rssi\":%d,"
      "\"last_rssi_age_ms\":%lu,\"last_heap\":%lu,\"wifi_status\":%d,\"rssi_dbm\":%d,"
      "\"disconnects\":%lu,\"last_disconnect_reason\":%u,\"last_disconnect_ms\":%lu,"
      "\"heap_free\":%lu,\"heap_min\":%lu}",
      node, (unsigned long)boot, (unsigned long)produced,
      (unsigned long)d.report, millis(),
      (unsigned long)d.attempted, (unsigned long)d.accepted, (unsigned long)d.failed,
      (unsigned long)d.dataFailed, (unsigned long)d.controlFailed,
      (unsigned long)d.stages[0], (unsigned long)d.stages[1],
      (unsigned long)d.stages[2], (unsigned long)d.stages[3],
      (unsigned long)d.errors[0], (unsigned long)d.errors[1],
      (unsigned long)d.errors[2], (unsigned long)d.errors[3],
      d.lastErrno, d.lastStage, d.lastData ? "true" : "false", (unsigned long)d.lastMs,
      (unsigned long)d.lastBytes, d.lastSent, d.lastWifi, d.lastRssi,
      (unsigned long)d.lastRssiAgeMs, (unsigned long)d.lastHeap,
      static_cast<int>(WiFi.status()), cachedRssi,
      (unsigned long)lostCount, reason, (unsigned long)lostMs,
      (unsigned long)ESP.getFreeHeap(), (unsigned long)ESP.getMinFreeHeap());
}
