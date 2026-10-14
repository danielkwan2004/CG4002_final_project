#include <WiFi.h>
#include <WiFiUdp.h>

// Set these to the 2.4 GHz hotspot used by both the FireBeetle and laptop.
const char *WIFI_SSID = "Reno13";
const char *WIFI_PASSWORD = "12345678";

const uint16_t TELEMETRY_PORT = 4210;
const unsigned long SEND_INTERVAL_MS = 2000;
const unsigned long RECONNECT_INTERVAL_MS = 10000;

// Leave empty to broadcast on the hotspot subnet. If broadcast is blocked,
// enter the laptop's hotspot IPv4 address here, for example "192.168.1.42".
const char *LAPTOP_IP = "172.25.110.89";

WiFiUDP udp;
bool udpReady = false;
unsigned long lastSendMs = 0;
unsigned long lastReconnectMs = 0;
uint32_t sequenceNumber = 0;

IPAddress destinationAddress() {
  if (LAPTOP_IP[0] != '\0') {
    IPAddress laptop;
    if (laptop.fromString(LAPTOP_IP)) {
      return laptop;
    }
  }

  IPAddress local = WiFi.localIP();
  IPAddress mask = WiFi.subnetMask();
  return IPAddress(local[0] | (mask[0] ^ 0xFF),
                   local[1] | (mask[1] ^ 0xFF),
                   local[2] | (mask[2] ^ 0xFF),
                   local[3] | (mask[3] ^ 0xFF));
}

void setup() {
  Serial.begin(115200);  // Optional USB diagnostics during initial setup.
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lastReconnectMs = millis();
}

void loop() {
  unsigned long now = millis();

  if (WiFi.status() != WL_CONNECTED) {
    if (udpReady) {
      udp.stop();
      udpReady = false;
    }
    if (now - lastReconnectMs >= RECONNECT_INTERVAL_MS) {
      Serial.println("Wi-Fi disconnected; reconnecting...");
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      lastReconnectMs = now;
    }
    return;
  }

  if (!udpReady) {
    udpReady = udp.begin(4211) == 1;
    if (!udpReady) {
      return;
    }
  }

  if (now - lastSendMs < SEND_INTERVAL_MS) {
    return;
  }
  lastSendMs = now;

  char message[160];
  IPAddress local = WiFi.localIP();
  snprintf(message, sizeof(message),
           "firebeetle_wifi_test seq=%lu uptime_ms=%lu rssi_dbm=%ld ip=%u.%u.%u.%u",
           static_cast<unsigned long>(++sequenceNumber),
           static_cast<unsigned long>(now),
           static_cast<long>(WiFi.RSSI()),
           local[0], local[1], local[2], local[3]);

  udp.beginPacket(destinationAddress(), TELEMETRY_PORT);
  udp.print(message);
  if (udp.endPacket() == 1) {
    Serial.println(message);
  } else {
    Serial.println("UDP send failed");
  }
}
