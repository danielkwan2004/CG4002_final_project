#include "WiFiTelemetry.h"

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

  // Default modem-sleep power saving periodically suspends the radio and
  // can silently drop bursts of outgoing UDP packets -- not needed on a
  // battery-fed node that streams continuously while awake.
  WiFi.setSleep(false);

  destinationPort = port;
  udp.begin(port);

  return true;
}

IPAddress WiFiTelemetry::localIP() const {
  return WiFi.localIP();
}

bool WiFiTelemetry::sendFrame(const SensorFrame& frame) {
  if (destinationPort == 0) {
    return false;
  }

    char packet[320];
  int length = snprintf(
      packet,
      sizeof(packet),
      "2,%u,%lu,%lu,%d,%d,%d,%d,%d,%d,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%u\n",
      frame.node_id,
      static_cast<unsigned int>(frame.seq),
      frame.timestamp_us,
      frame.ax,
      frame.ay,
      frame.az,
      frame.gx,
      frame.gy,
      frame.gz,
      frame.ax_g,
      frame.ay_g,
      frame.az_g,
      frame.gx_dps,
      frame.gy_dps,
      frame.gz_dps,
        frame.ax_filtered_g,
        frame.ay_filtered_g,
        frame.az_filtered_g,
        frame.gx_filtered_dps,
        frame.gy_filtered_dps,
        frame.gz_filtered_dps,
      frame.status_flags
  );

  if (length <= 0 || length >= static_cast<int>(sizeof(packet))) {
    return false;
  }

  if (!udp.beginPacket(laptopAddress, destinationPort)) {
    return false;
  }

  udp.write(reinterpret_cast<const uint8_t*>(packet), length);
  return udp.endPacket() == 1;
}
