#include "BleTelemetry.h"
#include <NimBLEDevice.h>

namespace {
portMUX_TYPE linkMux = portMUX_INITIALIZER_UNLOCKED;
BleLink sharedLink;
NimBLECharacteristic* sampleCharacteristic = nullptr;
NimBLECharacteristic* statusCharacteristic = nullptr;
NimBLEServer* server = nullptr;

class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* s, NimBLEConnInfo& info) override {
    portENTER_CRITICAL(&linkMux);
    bool occupied = sharedLink.handle != 0xffff;
    if (!occupied) {
      sharedLink.handle = info.getConnHandle();
      sharedLink.mtu = 23;
      sharedLink.subscribed = false;
      ++sharedLink.session;
    }
    portEXIT_CRITICAL(&linkMux);
    if (occupied) { s->disconnect(info.getConnHandle()); return; }
    s->updateConnParams(info.getConnHandle(), 6, 12, 0, 400);
  }
  void onDisconnect(NimBLEServer*, NimBLEConnInfo& info, int) override {
    portENTER_CRITICAL(&linkMux);
    if (sharedLink.handle == info.getConnHandle()) {
      sharedLink.handle = 0xffff; sharedLink.mtu = 23;
      sharedLink.subscribed = false; ++sharedLink.session;
    }
    portEXIT_CRITICAL(&linkMux);
  }
  void onMTUChange(uint16_t mtu, NimBLEConnInfo& info) override {
    portENTER_CRITICAL(&linkMux);
    if (sharedLink.handle == info.getConnHandle()) sharedLink.mtu = mtu;
    portEXIT_CRITICAL(&linkMux);
  }
};
class SampleCallbacks : public NimBLECharacteristicCallbacks {
  void onSubscribe(NimBLECharacteristic*, NimBLEConnInfo& info, uint16_t value) override {
    uint16_t mtu = info.getMTU();
    portENTER_CRITICAL(&linkMux);
    if (sharedLink.handle == info.getConnHandle()) {
      sharedLink.subscribed = (value & 1) != 0;
      sharedLink.mtu = mtu;
      ++sharedLink.session;
    }
    portEXIT_CRITICAL(&linkMux);
  }
};
ServerCallbacks serverCallbacks;
SampleCallbacks sampleCallbacks;
}

bool BleTelemetry::begin(const char* name, uint8_t node, uint32_t boot) {
  nodeId = node; bootId = boot;
  if (!NimBLEDevice::init(name)) return false;
  NimBLEDevice::setMTU(185);
  server = NimBLEDevice::createServer();
  if (!server) return false;
  server->setCallbacks(&serverCallbacks, false);
  server->advertiseOnDisconnect(false);  // loop retries failed advertising starts
  auto* service = server->createService(BLE_SERVICE_UUID);
  if (!service) return false;
  sampleCharacteristic = service->createCharacteristic(BLE_NOTIFY_UUID, NIMBLE_PROPERTY::NOTIFY);
  statusCharacteristic = service->createCharacteristic(BLE_STATUS_UUID, NIMBLE_PROPERTY::READ);
  if (!sampleCharacteristic || !statusCharacteristic) return false;
  sampleCharacteristic->setCallbacks(&sampleCallbacks);
  statusCharacteristic->setValue("{\"state\":\"BOOT\"}");
  if (!server->start()) return false;
  auto* advertising = NimBLEDevice::getAdvertising();
  if (!advertising->addServiceUUID(BLE_SERVICE_UUID)) return false;
  advertising->enableScanResponse(true);
  if (!advertising->setName(name)) return false;
  Serial.printf("[ble] %s; waiting for receiver subscription (MTU >= %u)\n", name, BLE_MIN_MTU);
  // A transient advertising failure is retried by service().
  advertising->start();
  return true;
}

BleLink BleTelemetry::link() const {
  portENTER_CRITICAL(&linkMux);
  BleLink result = sharedLink;
  portEXIT_CRITICAL(&linkMux);
  return result;
}
BleLink BleTelemetry::syncLink() {
  BleLink current = link();
  if (current.session != session) {
    queue.clear();  // never replay a previous connection/subscription's samples
    session = current.session;
  }
  return current;
}
void BleTelemetry::enqueue(const SensorFrame& frame, uint32_t burst, uint8_t event) {
  BleLink current = syncLink();
  if (!current.subscribed || current.mtu < BLE_MIN_MTU) { ++offline; return; }
  queue.enqueue(frame, burst, event, millis());
}
void BleTelemetry::service() {
  if (!server) return;
  BleLink current = syncLink();
  if (current.handle == 0xffff) {
    if (millis()-lastAdvertiseMs >= 1000) {
      lastAdvertiseMs = millis();
      auto* advertising = NimBLEDevice::getAdvertising();
      if (!advertising->isAdvertising() && !advertising->start())
        Serial.println("[ble] advertising failed; will retry");
    }
    return;
  }
  if (!current.subscribed) return;
  queue.service(millis(), current.mtu, nodeId, bootId, current.session,
      [current](const uint8_t* packet, size_t length) {
        return sampleCharacteristic->notify(packet, length, current.handle);
      });
}
void BleTelemetry::setStatus(const char* json) {
  if (statusCharacteristic) statusCharacteristic->setValue(json);
}
