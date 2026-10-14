#pragma once
class IPAddress {};
struct TestWiFi { IPAddress gatewayIP() { return {}; } };
inline TestWiFi WiFi;
