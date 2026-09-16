#include <NimBLEDevice.h>
#include <ArduinoJson.h>

#define SERVICE_UUID        "25E2CCC3-D857-49A6-AFDC-F6895F1854B0"
#define NOTIFY_CHAR_UUID    "2F752BBE-B112-4F11-9789-093262B39116"
#define WRITE_CHAR_UUID     "A9A6FB55-B997-4A3B-A9FA-D97C1E23DB5F"

#define NODE_ID "forearm"

enum PacketType : uint8_t {
    PKT_HELLO_REQ   = 0x01,
    PKT_HELLO       = 0x02,
    PKT_CONFIG      = 0x03,
    PKT_CONFIG_ACK  = 0x04,
    PKT_SYNC_REQ    = 0x05,
    PKT_SYNC_RESP   = 0x06,
    PKT_SENSOR_DATA = 0x07,
    PKT_HAPTIC_CMD  = 0x08,
};

enum ConnState { DISCONNECTED, CONNECTED, HELLO_SENT, CONFIGURED, SYNCHRONISED };
volatile ConnState state = DISCONNECTED;

volatile uint32_t connectedAt = 0;

volatile bool pendingHello = false;
volatile bool pendingConfigAck = false;
volatile bool pendingHapticAck = false;
volatile bool pendingSyncResp = false;

volatile uint32_t syncRequestId = 0;
volatile uint32_t syncNodeTimestamp = 0;
volatile uint32_t syncRespCount = 0;

NimBLECharacteristic* notifyChar;
NimBLECharacteristic* writeChar;
uint32_t seq = 0;
int configuredSampleRate = 200;

struct __attribute__((packed)) SensorPayload {
    uint8_t type = PKT_SENSOR_DATA;
    uint32_t sequence;
    uint32_t timestamp;
    float accel[3];
    float gyro[3];
};

class ServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo) {
        Serial.println("Client connected");
        state = CONNECTED;
        connectedAt = millis();
        pServer->updateConnParams(connInfo.getConnHandle(), 12, 24, 0, 100);
    }

    void onDisconnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo, int reason) {
        Serial.println("Client disconnected - reset state and restart advertising");
        state = DISCONNECTED;
        pendingHello = false;
        pendingConfigAck = false;
        pendingSyncResp = false;
        pendingHapticAck = false;
        syncRequestId = 0;
        syncNodeTimestamp = 0;
        syncRespCount = 0;
        NimBLEDevice::startAdvertising();
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
            configuredSampleRate = doc["sample_rate_hz"] | 200;
            pendingConfigAck = true;
        }
        else if (type == PKT_SYNC_REQ) {
            syncRequestId = doc["request_id"] | 0;
            syncNodeTimestamp = millis();
            pendingSyncResp = true;
        }
        else if (type == PKT_HAPTIC_CMD) {
            const char* pattern = doc["pattern"] | "none";
            Serial.print("HAPTIC_CMD received, pattern = ");
            Serial.println(pattern);
            // TODO (hardware); trigger actuatuor here 
            pendingHapticAck = true;
        }
    }
};

void setup() {
    Serial.begin(115200);
    NimBLEDevice::init(NODE_ID);
    NimBLEDevice::setSecurityAuth(true, true, true);
    NimBLEDevice::setSecurityIOCap(BLE_HS_IO_NO_INPUT_OUTPUT);

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
    advertising->setName(NODE_ID);
    advertising->start();

    Serial.println("Advertising started");
}

void loop() {
    // WATCHDOG: If connected but no HELLO_REQ received within 3 seconds, break ghost connection
    if (state == CONNECTED && connectedAt > 0 && (millis() - connectedAt > 3000)) {
        Serial.println("Ghost connection detected (no HELLO_REQ) - forcing disconnect");
        connectedAt = 0;
        NimBLEServer* server = NimBLEDevice::getServer();
        if (server && server->getConnectedCount() > 0) {
            server->disconnect(0);
        }
        state = DISCONNECTED;
        NimBLEDevice::startAdvertising();
    }

    // 1. HELLO handshake
    if (pendingHello) {
        pendingHello = false;
        connectedAt = 0;
        JsonDocument doc;
        doc["type"] = PKT_HELLO;
        doc["node_id"] = NODE_ID;
        JsonArray caps = doc["capabilities"].to<JsonArray>();
        caps.add("accel");
        caps.add("gyro");
        doc["calibrated"] = true;

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
        Serial.println("Sent CONFIG_ACK - now streaming");
    }

    // 3. Time Synchronisation Responses
    if (pendingSyncResp) {
        pendingSyncResp = false;
        syncRespCount++;
        JsonDocument doc;
        doc["type"] = PKT_SYNC_RESP;
        doc["request_id"] = syncRequestId;
        doc["node_timestamp"] = syncNodeTimestamp;

        String syncPkt;
        serializeJson(doc, syncPkt);
        notifyChar->setValue(syncPkt.c_str());
        notifyChar->notify();
        if (syncRespCount == 5) {
            state = SYNCHRONISED;
            syncRespCount = 0;
        }
        Serial.println("Sent SYNC_RESP");
    }

    // 4. Haptic ack
    if (pendingHapticAck) {
        pendingHapticAck = false;
        // optional: notify laptop that haptic was received
    }
    
    // 5. Stream SENSOR_DATA at 200Hz
    static uint32_t lastSample = 0;
    uint32_t interval = 1000 / configuredSampleRate;
    if (state == SYNCHRONISED && (millis() - lastSample >= interval)) {  
        lastSample = millis();
        seq++;

        SensorPayload sensorPkt;
        sensorPkt.sequence = seq;
        sensorPkt.timestamp = millis();

        sensorPkt.accel[0] = 1.0f;
        sensorPkt.accel[1] = 0.5f;
        sensorPkt.accel[2] = 9.8f;
        sensorPkt.gyro[0] = 0.0f;
        sensorPkt.gyro[1] = 0.0f;
        sensorPkt.gyro[2] = 0.0f;
        notifyChar->setValue((uint8_t*)&sensorPkt, sizeof(sensorPkt));
        notifyChar->notify();
    }
};