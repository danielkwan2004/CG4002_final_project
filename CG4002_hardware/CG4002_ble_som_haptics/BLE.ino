// Based on imu_wifi_battery_test/BLE.ino. Same encrypted GATT service,
// JSON handshake/sync/control messages and binary <II6f sensor records.
#include <NimBLEDevice.h>
#include <ArduinoJson.h>
#include "BleProtocol.h"
#include "HapticsConfig.h"

NimBLECharacteristic* notifyChar = nullptr;
NimBLECharacteristic* writeChar = nullptr;
NimBLEServer* bleServer = nullptr;
ConnState state = DISCONNECTED;
bool continuousSampling = true, streamingPaused = true, capturePending = false;
uint32_t captureStart = 0, seq = 0;
SensorBatchPayload sensorBatches[2];
uint32_t batchStartedMs[2] = {};

constexpr uint8_t TX_QUEUE_SIZE = 64, COMMAND_QUEUE_SIZE = 8;
Notification txQueue[TX_QUEUE_SIZE];
uint8_t txHead = 0, txCount = 0;
uint32_t nextNotifyAt = 0, nextAdvertisingAttempt = 0;
uint32_t droppedBatches = 0, acceptedBatches = 0, notifyRetries = 0;
uint32_t appliedGeneration = UINT32_MAX;
BleLinkState linkState;
portMUX_TYPE bleMux = portMUX_INITIALIZER_UNLOCKED;
BleCommand commands[COMMAND_QUEUE_SIZE];
uint8_t commandHead = 0, commandCount = 0;
uint32_t droppedCommands = 0;
std::string pendingReply;
int replyNextState = -1;
bool bleReady = false;

BleLinkState readBleLink() {
  portENTER_CRITICAL(&bleMux);
  BleLinkState result = linkState;
  portEXIT_CRITICAL(&bleMux);
  return result;
}

void clearSensorBuffers() {
  motionGate.suspend();
  txHead = txCount = 0;
  for (auto& batch : sensorBatches) batch.count = 0;
}

void applyLinkChanges() {
  const auto link = readBleLink();
  if (link.generation == appliedGeneration) return;
  appliedGeneration = link.generation;
  stopHaptics(); // Do not replay commands left over from a previous link/subscription.
  clearSensorBuffers();
  pendingReply.clear(); replyNextState = -1;
  streamingPaused = true; capturePending = false;
  state = link.handle == 0xffff ? DISCONNECTED : CONNECTED;
  nextNotifyAt = millis();
  Serial.printf("[ble] %s subscribed=%u mtu=%u; waiting for client handshake\n",
      state == DISCONNECTED ? "disconnected" : "connected", link.subscribed, link.mtu);
}

bool queueNotification(const void* data, size_t length) {
  if (txCount == TX_QUEUE_SIZE || length > sizeof(Notification::bytes)) return false;
  Notification& item = txQueue[(txHead + txCount) % TX_QUEUE_SIZE];
  memcpy(item.bytes, data, length); item.length = length; ++txCount;
  return true;
}

void sendSensorBatch(SensorBatchPayload& batch) {
  if (!batch.count) return;
  if (!queueNotification(&batch, 3 + batch.count * sizeof(SensorSample))) ++droppedBatches;
  batch.count = 0;
}

uint8_t sensorBatchLimit() {
  const auto link = readBleLink();
  if (!link.subscribed || link.mtu < 38) return 0; // 3 ATT + 3 header + 32 sample
  uint16_t count = (link.mtu - 6) / sizeof(SensorSample);
  return count < SENSOR_BATCH_SIZE ? static_cast<uint8_t>(count) : SENSOR_BATCH_SIZE;
}

void appendFrameSample(const SensorFrame& frame, uint32_t timestamp, uint8_t source) {
  uint8_t limit = sensorBatchLimit();
  if (!limit) return;
  SensorBatchPayload& batch = sensorBatches[source];
  batch.source = source;
  if (batch.count >= limit) sendSensorBatch(batch);
  if (!batch.count) batchStartedMs[source] = millis();
  SensorSample& sample = batch.samples[batch.count++];
  sample.sequence = ++seq; // Shared by normal and command-triggered capture, as supplied.
  sample.timestamp = timestamp;
  sample.accel[0] = frame.ax_filtered_g * 9.80665f;
  sample.accel[1] = frame.ay_filtered_g * 9.80665f;
  sample.accel[2] = frame.az_filtered_g * 9.80665f;
  sample.gyro[0] = frame.gx_filtered_dps;
  sample.gyro[1] = frame.gy_filtered_dps;
  sample.gyro[2] = frame.gz_filtered_dps;
  if (batch.count == limit) sendSensorBatch(batch);
}

void appendSensorSample(uint32_t timestamp, uint8_t source) {
  appendFrameSample(latestFrame,timestamp,source);
}

void ensureAdvertising() {
  if (!bleReady || state != DISCONNECTED || bleServer->getConnectedCount()) return;
  auto* advertising = NimBLEDevice::getAdvertising();
  uint32_t now = millis();
  if (advertising->isAdvertising() || static_cast<int32_t>(now-nextAdvertisingAttempt) < 0) return;
  nextAdvertisingAttempt = now + 1000;
  if (advertising->start()) Serial.printf("Advertising as %s\n", NODE_ID);
  else Serial.println("Advertising start failed; retrying in 1s");
}

class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* server, NimBLEConnInfo& info) override {
    portENTER_CRITICAL(&bleMux);
    bool occupied = linkState.handle != 0xffff;
    if (!occupied) {
      linkState.handle = info.getConnHandle(); linkState.mtu = info.getMTU();
      linkState.subscribed = false; ++linkState.generation;
    }
    portEXIT_CRITICAL(&bleMux);
    if (occupied) { server->disconnect(info.getConnHandle()); return; }
    server->updateConnParams(info.getConnHandle(), 6, 12, 0, 400);
  }
  void onDisconnect(NimBLEServer*, NimBLEConnInfo& info, int) override {
    portENTER_CRITICAL(&bleMux);
    if (linkState.handle == info.getConnHandle()) {
      linkState.handle = 0xffff; linkState.mtu = 23;
      linkState.subscribed = false; ++linkState.generation;
    }
    portEXIT_CRITICAL(&bleMux);
  }
  void onMTUChange(uint16_t mtu, NimBLEConnInfo& info) override {
    portENTER_CRITICAL(&bleMux);
    if (linkState.handle == info.getConnHandle()) linkState.mtu = mtu;
    portEXIT_CRITICAL(&bleMux);
  }
  void onAuthenticationComplete(NimBLEConnInfo& info) override {
    Serial.println(info.isEncrypted() ? "BLE link encrypted" : "BLE encryption failed");
  }
};
class NotifyCharCallbacks : public NimBLECharacteristicCallbacks {
  void onSubscribe(NimBLECharacteristic*, NimBLEConnInfo& info, uint16_t value) override {
    portENTER_CRITICAL(&bleMux);
    if (linkState.handle == info.getConnHandle()) {
      bool subscribed = (value & 1) != 0;
      if (subscribed != linkState.subscribed) ++linkState.generation;
      linkState.subscribed = subscribed; linkState.mtu = info.getMTU();
    }
    portEXIT_CRITICAL(&bleMux);
  }
};
class WriteCallback : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo& info) override {
    const uint32_t receivedMs = millis(); // Timestamp at receipt, before main-loop delay.
    std::string value = characteristic->getValue();
    portENTER_CRITICAL(&bleMux);
    if (info.getConnHandle() == linkState.handle && commandCount < COMMAND_QUEUE_SIZE &&
        value.size() < sizeof(BleCommand::json)) {
      BleCommand& command = commands[(commandHead + commandCount) % COMMAND_QUEUE_SIZE];
      memcpy(command.json, value.data(), value.size()); command.json[value.size()] = '\0';
      command.receivedMs = receivedMs; command.generation = linkState.generation;
      ++commandCount;
    } else ++droppedCommands;
    portEXIT_CRITICAL(&bleMux);
  }
};
ServerCallbacks serverCallbacks;
NotifyCharCallbacks notifyCallbacks;
WriteCallback writeCallbacks;

bool takeCommand(BleCommand& command) {
  portENTER_CRITICAL(&bleMux);
  bool available = commandCount != 0;
  if (available) { command = commands[commandHead]; commandHead = (commandHead+1)%COMMAND_QUEUE_SIZE; --commandCount; }
  portEXIT_CRITICAL(&bleMux);
  return available;
}

void processCommand() {
  if (!pendingReply.empty()) return; // Retry this reply before accepting another request.
  BleCommand command;
  if (!takeCommand(command)) return;
  // A subscription callback can arrive between loop's link check and this read.
  // Apply it before deciding whether this command belongs to an old connection.
  if (command.generation != appliedGeneration) applyLinkChanges();
  if (command.generation != appliedGeneration) return;
  JsonDocument doc;
  if (deserializeJson(doc, command.json)) { Serial.println("JSON parse failed"); return; }
  JsonDocument response;
  uint8_t type = doc["type"] | uint8_t(0);
  switch (type) {
    case PKT_HELLO_REQ: {
      response["type"] = PKT_HELLO;
      response["node_id"] = NODE_ID;
      JsonArray caps = response["capabilities"].to<JsonArray>(); caps.add("accel"); caps.add("gyro");
      response["calibrated"] = !calibrationFailed && nodeState == STREAMING;
      response["imu_status"] = nodeState == STREAMING ? "ok" : faultReason;
      replyNextState = HELLO_SENT;
      break;
    }
    case PKT_CONFIG:
      continuousSampling = doc["continuous"] | true;
      if (!continuousSampling) { clearSensorBuffers(); }
      response["type"] = PKT_CONFIG_ACK; response["status"] = "OK";
      replyNextState = CONFIGURED;
      break;
    case PKT_SYNC_START:
      streamingPaused = true; capturePending = false; clearSensorBuffers(); return;
    case PKT_SYNC_REQ:
      response["type"] = PKT_SYNC_RESP;
      response["request_id"] = doc["request_id"] | 0;
      response["node_timestamp"] = command.receivedMs;
      break;
    case PKT_SYNC_END:
      streamingPaused = false; state = SYNCHRONISED;
      Serial.println("Clock sync complete; motion-gated streaming enabled"); return;
    case PKT_DUMMY: {
      if (state != SYNCHRONISED || streamingPaused || capturePending ||
          !doc["start_timestamp"].is<uint32_t>()) return;
      uint32_t start = doc["start_timestamp"].as<uint32_t>();
      int32_t wait = static_cast<int32_t>(start-static_cast<uint32_t>(millis()));
      if (wait <= 0 || wait > 2000) return;
      captureStart = start; capturePending = true; return;
    }
    case PKT_HAPTIC_CMD: {
      HapticPattern pattern;
      response["type"] = PKT_HAPTIC_RESP;
      if (!parseHapticPattern(doc["pattern"].as<const char*>(), pattern)) {
        response["status"] = "ERROR"; response["reason"] = "invalid_pattern";
      } else if (!HapticsConfig::ENABLED) {
        response["status"] = "ERROR"; response["reason"] = "no_motor";
      } else if (!enqueueHapticPattern(pattern)) {
        response["status"] = "ERROR"; response["reason"] = "busy";
      } else {
        response["status"] = "OK"; // Accepted for playback, not a completion notification.
      }
      break;
    }
    default: return;
  }
  serializeJson(response, pendingReply);
}

void pumpNotifications(uint32_t now) {
  const auto link = readBleLink();
  if (!link.subscribed || link.generation != appliedGeneration ||
      static_cast<int32_t>(now-nextNotifyAt) < 0) return;
  bool control = !pendingReply.empty();
  if (!control && (!txCount || state != SYNCHRONISED || streamingPaused)) return;
  const uint8_t* data = control ? reinterpret_cast<const uint8_t*>(pendingReply.data()) : txQueue[txHead].bytes;
  size_t length = control ? pendingReply.size() : txQueue[txHead].length;
  nextNotifyAt = now + 2;
  if (length > static_cast<size_t>(link.mtu-3)) {
    // Never let NimBLE truncate the client's JSON or binary packet.
    static uint32_t lastWarning = 0;
    if (now-lastWarning >= 1000) { lastWarning=now; Serial.printf("[ble] MTU %u too small for %u-byte packet\n", link.mtu, (unsigned)length); }
    return;
  }
  if (!notifyChar->notify(data, length, link.handle)) { ++notifyRetries; return; }
  if (control) {
    Serial.printf("[ble] sent %s\n", pendingReply.c_str());
    pendingReply.clear();
    if (replyNextState >= 0) state = static_cast<ConnState>(replyNextState);
    replyNextState = -1;
  } else { txHead=(txHead+1)%TX_QUEUE_SIZE; --txCount; ++acceptedBatches; }
}

void printBleHealth() {
  Serial.printf("[haptic] enabled=%u running=%u waiting=%u\n",
      HapticsConfig::ENABLED, hapticsBusy(), pendingHapticPatterns());
  const auto link = readBleLink();
  portENTER_CRITICAL(&bleMux);
  uint32_t commandDrops = droppedCommands;
  portEXIT_CRITICAL(&bleMux);
  Serial.printf("[ble] name=%s state=%u subscribed=%u mtu=%u paused=%u continuous=%u ble_seq=%lu accepted_batches=%lu pending_batches=%u dropped_batches=%lu retries=%lu command_drops=%lu\n",
      NODE_ID, state, link.subscribed, link.mtu, streamingPaused, continuousSampling,
      (unsigned long)seq, (unsigned long)acceptedBatches, txCount, (unsigned long)droppedBatches,
      (unsigned long)notifyRetries, (unsigned long)commandDrops);
}

void setup() {
  Serial.begin(115200);
  setupSensor(); // Finish calibration before advertising; no handshake timeout during calibration.
  if (!NimBLEDevice::init(NODE_ID)) { enterFault("ble_startup", false); return; }
  NimBLEDevice::setMTU(185);
  NimBLEDevice::setSecurityAuth(true, false, true);
  NimBLEDevice::setSecurityIOCap(BLE_HS_IO_NO_INPUT_OUTPUT);
  bleServer = NimBLEDevice::createServer();
  if (!bleServer) { enterFault("ble_server", false); return; }
  bleServer->setCallbacks(&serverCallbacks, false);
  bleServer->advertiseOnDisconnect(false);
  auto* service = bleServer->createService(SERVICE_UUID);
  if (!service) { enterFault("ble_service", false); return; }
  notifyChar = service->createCharacteristic(NOTIFY_CHAR_UUID, NIMBLE_PROPERTY::NOTIFY | NIMBLE_PROPERTY::READ_ENC);
  writeChar = service->createCharacteristic(WRITE_CHAR_UUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_ENC);
  if (!notifyChar || !writeChar) { enterFault("ble_characteristic", false); return; }
  notifyChar->setCallbacks(&notifyCallbacks);
  writeChar->setCallbacks(&writeCallbacks);
  if (!bleServer->start()) { enterFault("ble_service_start", false); return; }
  auto* advertising = NimBLEDevice::getAdvertising();
  // Same advertisement as the reference: UUID and short forearm/paddle name.
  if (!advertising->addServiceUUID(SERVICE_UUID) || !advertising->setName(NODE_ID)) {
    enterFault("ble_advertisement", false); return;
  }
  bleReady = true; ensureAdvertising();
  nextSampleUs = micros(); // BLE initialization must not create a sampling backlog.
}

void loop() {
  const bool fresh = pollSensor(); // Calibration/LPF/gate are independent of BLE state.
  if (!bleReady) return;
  applyLinkChanges();
  ensureAdvertising();
  processCommand();
  const uint32_t now = millis();
  if (state == SYNCHRONISED && !streamingPaused && readBleLink().subscribed) {
    if (capturePending && static_cast<int32_t>(now-(captureStart+CAPTURE_DURATION_MS)) >= 0) {
      capturePending = false; sendSensorBatch(sensorBatches[1]);
    }
    if (fresh) {
      if (continuousSampling) {
        const bool wasArmed=motionGate.armed();
        motionGate.process(latestFrame,sampleTimestampMs,[](const SensorFrame& frame,uint32_t ms) {
          appendFrameSample(frame,ms,0);
        });
        if (!wasArmed && motionGate.armed()) Serial.println("[motion] READY: local reference installed; motion-gated BLE enabled");
        if (motionGate.justEnded) sendSensorBatch(sensorBatches[0]);
      }
      // Preserve the client's explicit one-second source-1 capture, even when still.
      if (capturePending && static_cast<int32_t>(sampleTimestampMs-captureStart) >= 0 &&
          static_cast<int32_t>(sampleTimestampMs-(captureStart+CAPTURE_DURATION_MS)) < 0)
        appendSensorSample(sampleTimestampMs, 1);
    }
    for (uint8_t source=0; source<2; ++source)
      if (sensorBatches[source].count && now-batchStartedMs[source] >= 25)
        sendSensorBatch(sensorBatches[source]);
  }
  // One notification attempt per sample period; avoid starting it just before a read.
  static uint32_t lastServiceUs = 0;
  uint32_t started = micros();
  if (started-lastServiceUs < PERIOD_US ||
      (nodeState == STREAMING && static_cast<int32_t>(nextSampleUs-started) <= 3500)) return;
  lastServiceUs = started;
  pumpNotifications(now);
  uint32_t cost = micros()-started;
  if (cost > maxServiceUs) maxServiceUs = cost;
}
