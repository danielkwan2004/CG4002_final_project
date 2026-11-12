// Standalone file-transfer firmware.
#include <NimBLEDevice.h>
#include <ArduinoJson.h>
#include <LittleFS.h>
#include <mbedtls/sha256.h>
#include <mbedtls/version.h>

#define SERVICE_UUID        "25E2CCC3-D857-49A6-AFDC-F6895F1854B0"
#define NOTIFY_CHAR_UUID    "2F752BBE-B112-4F11-9789-093262B39116"
#define WRITE_CHAR_UUID     "A9A6FB55-B997-4A3B-A9FA-D97C1E23DB5F"

#define NODE_ID             "file-trf"
#define DEMO_FILE_PATH      "/demo.txt"

constexpr size_t DEMO_FILE_SIZE = 128 * 1024;
const char DEMO_FILE_PATTERN[] =
    "FireBeetle BLE file-transfer throughput test 0123456789abcdef\n";

enum PacketType : uint8_t {
    PKT_FILE_REQ       = 0x11,
    PKT_FILE_META      = 0x12,
    PKT_FILE_CHUNK     = 0x13,
    PKT_FILE_CHUNK_REQ = 0x14,
    PKT_FILE_RESULT    = 0x15,
};

// ATT MTU 185 allows up to 182 bytes of notification data.
// 6-byte header + 160-byte content = 166 bytes.
constexpr size_t CHUNK_SIZE = 160;
constexpr size_t CHUNK_HEADER_SIZE = 6;
constexpr uint8_t CHUNKS_PER_BATCH = 16;
constexpr uint8_t NOTIFY_SEND_ATTEMPTS = 10;
constexpr uint8_t NOTIFY_RETRY_DELAY_MS = 1;

NimBLECharacteristic* notifyChar = nullptr;
volatile bool connected = false;
volatile bool metadataRequested = false;
volatile bool chunkBatchRequested = false;
volatile uint16_t transferId = 0;
volatile uint16_t requestedBatchStart = 0;
volatile uint8_t requestedBatchCount = 0;


// Hash file contents in small blocks rather than loading the full file into RAM.
// This transfer-integrity SHA-256 is separate from submission ZIP MD5 hashes.
String fileSHA256() {
    File file = LittleFS.open(DEMO_FILE_PATH, "r");
    if (!file) return "";

    mbedtls_sha256_context context;
    mbedtls_sha256_init(&context);
#if MBEDTLS_VERSION_MAJOR >= 3
    mbedtls_sha256_starts(&context, 0);
#else
    mbedtls_sha256_starts_ret(&context, 0);
#endif

    uint8_t digest[32];
    uint8_t buffer[256];
    while (file.available()) {
        size_t count = file.read(buffer, sizeof(buffer));
#if MBEDTLS_VERSION_MAJOR >= 3
        mbedtls_sha256_update(&context, buffer, count);
#else
        mbedtls_sha256_update_ret(&context, buffer, count);
#endif
    }
    file.close();
#if MBEDTLS_VERSION_MAJOR >= 3
    mbedtls_sha256_finish(&context, digest);
#else
    mbedtls_sha256_finish_ret(&context, digest);
#endif
    mbedtls_sha256_free(&context);

    const char hex[] = "0123456789abcdef";
    char output[65];
    for (size_t index = 0; index < sizeof(digest); index++) {
        output[index * 2] = hex[digest[index] >> 4];
        output[index * 2 + 1] = hex[digest[index] & 0x0F];
    }
    output[64] = '\0';
    return String(output);
}


bool sendBytes(const uint8_t* data, size_t length) {
    if (!connected) return false;

    for (uint8_t attempt = 0; attempt < NOTIFY_SEND_ATTEMPTS; attempt++) {
        if (notifyChar->notify(data, length)) return true;

        // Let the NimBLE host task drain its transmit queue, then retry.
        delay(NOTIFY_RETRY_DELAY_MS);
    }
    return false;
}


bool sendJson(JsonDocument& document) {
    String packet;
    serializeJson(document, packet);
    return sendBytes(
        reinterpret_cast<const uint8_t*>(packet.c_str()),
        packet.length()
    );
}


bool createDemoFile() {
    if (LittleFS.exists(DEMO_FILE_PATH)) {
        File existingFile = LittleFS.open(DEMO_FILE_PATH, "r");
        bool correctSize = existingFile && existingFile.size() == DEMO_FILE_SIZE;
        existingFile.close();
        if (correctSize) return true;

        // Replace the old demo automatically whenever DEMO_FILE_SIZE is changed.
        LittleFS.remove(DEMO_FILE_PATH);
    }

    File file = LittleFS.open(DEMO_FILE_PATH, "w");
    if (!file) return false;

    const uint8_t* pattern =
        reinterpret_cast<const uint8_t*>(DEMO_FILE_PATTERN);
    constexpr size_t patternSize = sizeof(DEMO_FILE_PATTERN) - 1;
    size_t remaining = DEMO_FILE_SIZE;

    while (remaining > 0) {
        // How many characters to write each time
        size_t writeSize = remaining < patternSize ? remaining : patternSize;
        if (file.write(pattern, writeSize) != writeSize) {
            file.close();
            LittleFS.remove(DEMO_FILE_PATH);
            return false;
        }
        remaining -= writeSize;
    }

    file.close();
    return true;
}


void sendMetadata() {
    File file = LittleFS.open(DEMO_FILE_PATH, "r");
    if (!file) {
        Serial.println("Could not open demo.txt");
        return;
    }

    size_t size = file.size();
    file.close();

    JsonDocument document;
    document["type"] = PKT_FILE_META;
    document["transfer_id"] = transferId;
    document["filename"] = "demo.txt";
    document["size"] = size;
    document["total_chunks"] = (size + CHUNK_SIZE - 1) / CHUNK_SIZE;
    String sha256 = fileSHA256();
    document["sha256"] = sha256;

    Serial.print("Original SHA-256: ");
    Serial.println(sha256);

    if (sendJson(document)) {
        Serial.println("Sent file metadata");
    } else {
        Serial.println("Could not send file metadata; laptop may request it again");
    }
}


// The laptop requests an index range, then requests individual missing chunks.
// File bytes use binary packets; metadata and transfer controls use JSON.
void sendChunkBatch(uint16_t startIndex, uint8_t count) {
    if (count == 0 || count > CHUNKS_PER_BATCH) return;

    File file = LittleFS.open(DEMO_FILE_PATH, "r");
    if (!file) return;

    size_t fileSize = file.size();
    size_t offset = static_cast<size_t>(startIndex) * CHUNK_SIZE;
    if (offset >= fileSize || !file.seek(offset, SeekSet)) {
        file.close();
        return;
    }

    for (uint8_t batchOffset = 0; batchOffset < count; batchOffset++) {
        uint16_t chunkIndex = startIndex + batchOffset;
        size_t chunkOffset = static_cast<size_t>(chunkIndex) * CHUNK_SIZE;
        if (chunkOffset >= fileSize) break;

        uint8_t packet[CHUNK_HEADER_SIZE + CHUNK_SIZE];
        packet[0] = PKT_FILE_CHUNK;
        packet[1] = static_cast<uint8_t>(transferId);
        packet[2] = static_cast<uint8_t>(transferId >> 8);
        packet[3] = static_cast<uint8_t>(chunkIndex);
        packet[4] = static_cast<uint8_t>(chunkIndex >> 8);

        size_t bytesRemaining = fileSize - chunkOffset;
        size_t requestedBytes =
            bytesRemaining < CHUNK_SIZE ? bytesRemaining : CHUNK_SIZE;
        size_t dataLength = file.read(
            packet + CHUNK_HEADER_SIZE,
            requestedBytes
        );
        packet[5] = static_cast<uint8_t>(dataLength);

        size_t packetLength = CHUNK_HEADER_SIZE + dataLength;
        if (!sendBytes(packet, packetLength)) {
            Serial.printf(
                "Could not send chunk %u; laptop will repair it\n",
                chunkIndex
            );
        }

        // Yield briefly so a 16-packet burst does not starve NimBLE's task.
        delay(1);
    }

    file.close();
}


class ServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* server, NimBLEConnInfo& connectionInfo) override {
        connected = true;
        server->updateConnParams(connectionInfo.getConnHandle(), 6, 12, 0, 100);
        Serial.println("Laptop connected");
    }

    void onDisconnect(
        NimBLEServer* server,
        NimBLEConnInfo& connectionInfo,
        int reason
    ) override {
        connected = false;
        metadataRequested = false;
        chunkBatchRequested = false;
        NimBLEDevice::startAdvertising();
        Serial.println("Laptop disconnected; advertising restarted");
    }

    void onAuthenticationComplete(NimBLEConnInfo& connectionInfo) override {
        Serial.println(connectionInfo.isEncrypted() ? "BLE link encrypted" : "BLE encryption failed");
    }

};


class WriteCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo& connectionInfo) override {
        std::string value = characteristic->getValue();
        JsonDocument document;
        DeserializationError error = deserializeJson(document, value);
        if (error) return;

        uint8_t type = document["type"] | 0;
        uint16_t packetTransferId = document["transfer_id"] | 0;

        if (type == PKT_FILE_REQ) {
            const char* filename = document["filename"] | "";
            if (!strcmp(filename, DEMO_FILE_PATH)) {
                transferId = packetTransferId;
                metadataRequested = true;
            }
        } else if (type == PKT_FILE_CHUNK_REQ && packetTransferId == transferId) {
            uint16_t batchStart = document["chunk_index"] | 0;
            uint8_t batchCount = document["count"] | 1;
            if (batchCount > 0 && batchCount <= CHUNKS_PER_BATCH) {
                requestedBatchStart = batchStart;
                requestedBatchCount = batchCount;
                chunkBatchRequested = true;
            }
        } else if (type == PKT_FILE_RESULT && packetTransferId == transferId) {
            const char* status = document["status"] | "ERROR";
            Serial.printf("Laptop file verification result: %s\n", status);
        }
    }
};


void setup() {
    Serial.begin(115200);

    if (!LittleFS.begin(true) || !createDemoFile()) {
        Serial.println("Could not initialise the demo file");
        return;
    }

    File file = LittleFS.open(DEMO_FILE_PATH, "r");
    Serial.printf("Demo file ready: %s (%u bytes)\n", DEMO_FILE_PATH, file.size());
    file.close();

    NimBLEDevice::init(NODE_ID);
    NimBLEDevice::setMTU(185);
    NimBLEDevice::setSecurityAuth(true, false, true);
    NimBLEDevice::setSecurityIOCap(BLE_HS_IO_NO_INPUT_OUTPUT);

    NimBLEServer* server = NimBLEDevice::createServer();
    server->setCallbacks(new ServerCallbacks());
    NimBLEService* service = server->createService(SERVICE_UUID);

    notifyChar = service->createCharacteristic(
        NOTIFY_CHAR_UUID,
        NIMBLE_PROPERTY::NOTIFY | NIMBLE_PROPERTY::READ_ENC
    );
    NimBLECharacteristic* writeChar = service->createCharacteristic(
        WRITE_CHAR_UUID,
        NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_ENC
    );
    writeChar->setCallbacks(new WriteCallbacks());

    service->start();
    NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
    advertising->addServiceUUID(SERVICE_UUID);
    advertising->setName(NODE_ID);
    advertising->start();
    Serial.printf("Advertising as %s\n", NODE_ID);
}


void loop() {
    if (metadataRequested) {
        metadataRequested = false;
        sendMetadata();
    }

    if (chunkBatchRequested) {
        chunkBatchRequested = false;
        sendChunkBatch(requestedBatchStart, requestedBatchCount);
    }
}
