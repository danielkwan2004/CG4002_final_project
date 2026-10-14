// Sensor firmware: JSON controls arrive over BLE writes; sensor readings
// leave as binary notifications. Set NODE_ID separately when flashing each board.
#include <NimBLEDevice.h>
#include <ArduinoJson.h>

#define SERVICE_UUID        "25E2CCC3-D857-49A6-AFDC-F6895F1854B0"
#define NOTIFY_CHAR_UUID    "2F752BBE-B112-4F11-9789-093262B39116"
#define WRITE_CHAR_UUID     "A9A6FB55-B997-4A3B-A9FA-D97C1E23DB5F"

#define NODE_ID "paddle" // flash with "forearm" or "paddle"

enum PacketType : uint8_t {
    PKT_HELLO_REQ    = 0x01,
    PKT_HELLO        = 0x02,
    PKT_CONFIG       = 0x03,
    PKT_CONFIG_ACK   = 0x04,

    PKT_SYNC_START   = 0x05,
    PKT_SYNC_REQ     = 0x06,
    PKT_SYNC_RESP    = 0x07,
    PKT_SYNC_END     = 0x08,

    PKT_SENSOR_BATCH = 0x09,

    PKT_HAPTIC_CMD   = 0x0C,
    PKT_HAPTIC_RESP  = 0X0D,

    PKT_DUMMY        = 0x0E,
};

constexpr uint8_t SENSOR_BATCH_SIZE = 5;

enum ConnState { DISCONNECTED, CONNECTED, HELLO_SENT, CONFIGURED, SYNCHRONISED };
volatile ConnState state = DISCONNECTED;

// Handshake
volatile bool pendingHello = false;
volatile bool pendingConfigAck = false;
volatile bool pendingHapticAck = false;
volatile bool pendingSyncResp = false;

// Clock syncing
volatile uint32_t syncRequestId = 0;
volatile uint32_t syncNodeTimestamp = 0;
volatile bool streamingPaused = true;

NimBLECharacteristic* notifyChar;
NimBLECharacteristic* writeChar;
uint32_t seq = 0;

// The IMU produces fresh readings at 200 Hz; pollImu() gates sampling.

// Keystroke capture
constexpr uint32_t CAPTURE_DURATION_MS = 1000;

volatile bool continuousSampling = true;
volatile bool capturePending = false;
volatile uint32_t captureStart = 0;
volatile bool resetSensorBuffers = false;

// Match Python <II6f exactly: no padding, milliseconds since boot, six float32s.
// Sequence is shared across stream and dummy, so either source alone can have gaps.
struct __attribute__((packed)) SensorSample {
    uint32_t sequence;
    uint32_t timestamp;
    float accel[3];
    float gyro[3];
};

// Source tags the entire batch. Stream and dummy use separate batch buffers,
// so the laptop never has to infer the source from sensor values.
struct __attribute__((packed)) SensorBatchPayload {
    uint8_t type = PKT_SENSOR_BATCH;
    uint8_t count = 0;
    uint8_t source = 0; // 0 = normal, 1 = dummy;
    SensorSample samples[SENSOR_BATCH_SIZE];
};

static_assert(sizeof(SensorSample) == 32, "Unexpected sensor sample layout");
static_assert(sizeof(SensorBatchPayload) == 3 + SENSOR_BATCH_SIZE * 32, "Unexpected sensor batch layout");

void sendSensorBatch(SensorBatchPayload& sensorBatch);

SensorBatchPayload sensorBatches[2]; // Independent normal and dummy buffers

// Buffer temporary BLE backpressure without blocking the 5 ms sampler.
// Both sources use this FIFO, preserving order within each source.
// This bounded queue absorbs short congestion; it cannot guarantee delivery.
// A full queue drops a batch, and the receiver may discard late queued samples.
constexpr uint8_t TX_QUEUE_SIZE = 64;
struct Notification {
    uint8_t bytes[sizeof(SensorBatchPayload)];
    size_t length;
};
Notification txQueue[TX_QUEUE_SIZE];
uint8_t txHead = 0, txCount = 0;
uint32_t nextNotifyAt = 0;
uint32_t droppedBatches = 0;

bool queueNotification(const void* data, size_t length) {
    if (txCount == TX_QUEUE_SIZE) return false;
    Notification& item = txQueue[(txHead + txCount) % TX_QUEUE_SIZE];
    memcpy(item.bytes, data, length);
    item.length = length;
    ++txCount;
    return true;
}

void pumpNotifications(uint32_t now) {
    if (!txCount || static_cast<int32_t>(now - nextNotifyAt) < 0) return;
    Notification& item = txQueue[txHead];
    if (notifyChar->notify(item.bytes, item.length)) {
        txHead = (txHead + 1) % TX_QUEUE_SIZE;
        --txCount;
    }
    // A failed notify stays queued; never spin or block the sampler waiting for BLE.
    nextNotifyAt = now + 2;
}

void sendSensorBatch(SensorBatchPayload& sensorBatch) {
    const size_t length = 3 + sensorBatch.count * sizeof(SensorSample);
    if (!queueNotification(&sensorBatch, length)) {
        ++droppedBatches;
        Serial.printf("BLE queue full: dropped batches=%lu\n", (unsigned long)droppedBatches);
    }
    sensorBatch.count = 0;
}

// Append a new sample to the sensor batch
void appendSensorSample(uint32_t timestamp, uint8_t source) {
    SensorBatchPayload& sensorBatch = sensorBatches[source];
    sensorBatch.source = source;
    SensorSample& sample = sensorBatch.samples[sensorBatch.count];
    sample.sequence = ++seq;
    sample.timestamp = timestamp;

    // Latest fresh ICM-42686-P sample, in native sensor axes.
    // +/-16 g: 2048 LSB/g; +/-2000 degrees/s: 16.4 LSB/(degrees/s).
    // Acceleration is m/s^2 (includes gravity), gyro is degrees/s.
    for (uint8_t axis = 0; axis < 3; ++axis) {
        sample.accel[axis] = (latest[axis] / 2048.0f) * 9.80665f;
        sample.gyro[axis] = latest[axis + 3] / 16.4f;
    }

    sensorBatch.count++;
    if (sensorBatch.count == SENSOR_BATCH_SIZE) sendSensorBatch(sensorBatch);
}

// Retry failed advertising starts; never claim success without checking it.
uint32_t nextAdvertisingAttempt = 0;
void ensureAdvertising() {
    if (state != DISCONNECTED || NimBLEDevice::getServer()->getConnectedCount() != 0) return;
    NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
    if (advertising->isAdvertising()) return;
    const uint32_t now = millis();
    if (static_cast<int32_t>(now - nextAdvertisingAttempt) < 0) return;
    nextAdvertisingAttempt = now + 1000;
    if (advertising->start()) Serial.printf("Advertising as %s\n", NODE_ID);
    else Serial.println("Advertising start failed; retrying in 1s");
}

class ServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo) {
        Serial.println("Laptop connected");
        state = CONNECTED;
        nextNotifyAt = millis();
        pServer->updateConnParams(connInfo.getConnHandle(), 6, 12, 0, 400);
    }

    void onDisconnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo, int reason) {
        Serial.printf("Client disconnected (reason=%d) - restarting advertising\n", reason);
        state = DISCONNECTED;
        resetSensorBuffers = true;
        pendingHello = false;
        pendingConfigAck = false;
        pendingSyncResp = false;
        pendingHapticAck = false;
        syncRequestId = 0;
        syncNodeTimestamp = 0;
        streamingPaused = true;
        capturePending = false;
        // loop() restarts advertising and retries if the BLE host is not ready.
    }

    void onAuthenticationComplete(NimBLEConnInfo& connInfo) override {
        if (connInfo.isEncrypted()) {
            Serial.println("--> BLE Link Encrypted Succesfully <--");
        } else {
            Serial.println("--> BLE Encryption Failed <--");
        }
    }
};

class NotifyCharCallbacks : public NimBLECharacteristicCallbacks {
    void onSubscribe(NimBLECharacteristic* pChar, NimBLEConnInfo& connInfo, uint16_t subValue) {
        if (subValue > 0 && state == CONNECTED) {
            Serial.println("Notifications enabled by laptop");
        }
    }
};

class WriteCallback : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pChar, NimBLEConnInfo& connInfo) {
        std::string value = pChar->getValue();

        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, value);
        if (err) {
            Serial.print("JSON parse failed: ");
            Serial.println(err.c_str());
            return;
        }

        uint8_t type = doc["type"] | 0;
        if (!type) return;

        if (type == PKT_HELLO_REQ) {
            pendingHello = true;
            Serial.println("Received HELLO_REQ from laptop");
        } 
        else if (type == PKT_CONFIG) {
            continuousSampling = doc["continuous"] | true;
            pendingConfigAck = true;
        }
        else if (type == PKT_SYNC_START) {
            streamingPaused = true;
            capturePending = false;
            resetSensorBuffers = true;
        }
        else if (type == PKT_SYNC_REQ) {
            syncRequestId = doc["request_id"] | 0;
            syncNodeTimestamp = millis();
            pendingSyncResp = true;
        }
        else if (type == PKT_SYNC_END) {
            streamingPaused = false;
            state = SYNCHRONISED;
        }
        else if (type == PKT_DUMMY) {
            if (state != SYNCHRONISED || streamingPaused || capturePending) return;
            if (!doc["start_timestamp"].is<uint32_t>()) return;
            const uint32_t start = doc["start_timestamp"].as<uint32_t>();
            const int32_t delayMs = static_cast<int32_t>(start - millis());
            if (delayMs <= 0 || delayMs > 2000) return;
            captureStart = start;
            capturePending = true;
        }
        // Only forearm node receives
        else if (type == PKT_HAPTIC_CMD) {
            const char* pattern = doc["pattern"] | "none";
            Serial.print("HAPTIC_CMD received, pattern = ");
            Serial.println(pattern);
            // TODO (hardware): trigger actuator here
            pendingHapticAck = true;
        }
    }
};

void setup() {
    Serial.begin(115200); // Optional diagnostics; never waits for USB.
    Wire.begin(SDA_PIN, SCL_PIN);
    Wire.setClock(400000);
    Wire.setTimeOut(20);
    startImu();
    lastImuTryMs = millis();
    Serial.printf("IMU: %s (I2C address 0x%02X)\n", imuState, imuAddress);
    NimBLEDevice::init(NODE_ID);
    NimBLEDevice::setMTU(185);
    NimBLEDevice::setSecurityAuth(true, false, true);
    NimBLEDevice::setSecurityIOCap(BLE_HS_IO_NO_INPUT_OUTPUT);
    // NimBLEDevice::deleteAllBonds();

    NimBLEServer* server = NimBLEDevice::createServer();
    server->setCallbacks(new ServerCallbacks());

    NimBLEService* service = server->createService(SERVICE_UUID);

    notifyChar = service->createCharacteristic(
        NOTIFY_CHAR_UUID,
        NIMBLE_PROPERTY::NOTIFY | NIMBLE_PROPERTY::READ_ENC
    );
    notifyChar->setCallbacks(new NotifyCharCallbacks());

    writeChar = service->createCharacteristic(
        WRITE_CHAR_UUID,
        NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_ENC
    );
    writeChar->setCallbacks(new WriteCallback());

    service->start();

    NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
    advertising->addServiceUUID(SERVICE_UUID);
    if (!advertising->setName(NODE_ID)) Serial.println("Failed to put node name in advertisement");
    ensureAdvertising();
}

void loop() {
    // Acquire independently of BLE handshake/streaming state.
    if (!imuReady && millis() - lastImuTryMs >= RETRY_MS) {
        startImu();
        lastImuTryMs = millis();
        Serial.printf("IMU: %s (I2C address 0x%02X)\n", imuState, imuAddress);
    }
    const bool freshImuSample = pollImu();
    const uint32_t sampleTimestamp = millis();
    ensureAdvertising();
    // BLE callbacks run on another task. Only loop() owns the sample/TX queues.
    if (resetSensorBuffers) {
        resetSensorBuffers = false;
        txHead = txCount = 0;
        for (auto& batch : sensorBatches) batch.count = 0;
    }
    // The laptop owns setup deadlines and disconnects failed attempts.

    // 1. HELLO handshake
    if (pendingHello) {
        pendingHello = false;
        JsonDocument doc;
        doc["type"] = PKT_HELLO;
        doc["node_id"] = NODE_ID;
        JsonArray caps = doc["capabilities"].to<JsonArray>();
        caps.add("accel");
        caps.add("gyro");
        doc["calibrated"] = false; // Raw scaled readings; no bias calibration applied.
        doc["imu_status"] = imuState;

        String helloPkt;
        serializeJson(doc, helloPkt);

        notifyChar->setValue(helloPkt.c_str());
        notifyChar->notify();
        state = HELLO_SENT;
        Serial.println("HELLO sent");
    }

    // 2. Config ack
    if (pendingConfigAck) {
        pendingConfigAck = false;
        JsonDocument doc;
        doc["type"] = PKT_CONFIG_ACK;
        doc["status"] = "OK";

        String ackPkt;
        serializeJson(doc, ackPkt);

        notifyChar->setValue(ackPkt.c_str());
        notifyChar->notify();
        state = CONFIGURED;
        Serial.println("Sent CONFIG_ACK - waiting for clock sync");
    }

    // 3. Clock synchronisation responses
    if (pendingSyncResp) {
        pendingSyncResp = false;
        JsonDocument doc;
        doc["type"] = PKT_SYNC_RESP;
        doc["request_id"] = syncRequestId;
        doc["node_timestamp"] = syncNodeTimestamp;

        String syncPkt;
        serializeJson(doc, syncPkt);
        notifyChar->setValue(syncPkt.c_str());
        notifyChar->notify();
        Serial.println("Sent SYNC_RESP");
        return;
    }

    // 4. Haptic ack
    if (pendingHapticAck) {
        pendingHapticAck = false;
        JsonDocument doc;
        doc["type"] = PKT_HAPTIC_RESP;
        doc["status"] = "OK";

        String ackPkt;
        serializeJson(doc, ackPkt);
        notifyChar->setValue(ackPkt.c_str());
        notifyChar->notify();
        Serial.println("Sent HAPTIC_RESP");
    }

    // 5. Append fresh readings to the streaming and keyboard-capture batches.
    if (state != SYNCHRONISED || streamingPaused) return;
    const uint32_t now = millis();
    if (capturePending &&
        static_cast<int32_t>(now - (captureStart + CAPTURE_DURATION_MS)) >= 0) {
        capturePending = false;
        // Flush a short final batch if a delayed loop collected fewer samples.
        if (sensorBatches[1].count) sendSensorBatch(sensorBatches[1]);
    }

    const bool captureActive = capturePending &&
        static_cast<int32_t>(now - captureStart) >= 0;

    // A single physical reading can belong to both source-tagged streams.
    // Read the IMU once, so capture cannot consume the normal stream's data-ready
    // flag. Missing sensor updates are skipped; stale values are never replayed.
    if (freshImuSample) {
        if (continuousSampling) appendSensorSample(sampleTimestamp, 0);
        if (captureActive &&
            static_cast<int32_t>(sampleTimestamp - captureStart) >= 0 &&
            static_cast<int32_t>(sampleTimestamp - (captureStart + CAPTURE_DURATION_MS)) < 0)
            appendSensorSample(sampleTimestamp, 1);
    }
    pumpNotifications(now);
}
