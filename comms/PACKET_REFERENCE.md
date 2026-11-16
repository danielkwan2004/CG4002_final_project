# Stream, result and haptic packet reference

Reference for the final BLE → laptop → MQTT → DPU pipeline. JSON examples use
decimal packet IDs; hex IDs below refer to the same numbers. JSON field order
does not matter. BLE sensor batches are binary; control and MQTT payloads are JSON.

The laptop submission contains the relay and shared protocol definitions.
This reference documents stream mode; `source=1` (`dummy`) and type 14 are retained
for optional test compatibility but are not used in the final operating procedure.
See [the setup guide](README.md) for startup and integration.

## Quick lookup

| Packet | Type (hex / decimal) | Route | Transport / topic |
|---|---|---|---|
| Sensor batch | `0x09` / `9` | Each FireBeetle → laptop | BLE notification, binary |
| Paired sensor data | `0x0A` / `10` | Laptop → Ultra96 | MQTT `fb/sensor/raw`, QoS 0 |
| AI result | `0x0B` / `11` | Ultra96 → result subscribers | MQTT `ultra96/ai/results`, QoS 1 |
| Haptic command | `0x0C` / `12` | Ultra96 → laptop → forearm FireBeetle | MQTT `ultra96/ai/haptics`, QoS 1, then BLE write |
| Haptic response | `0x0D` / `13` | Forearm FireBeetle → laptop | BLE notification |

## 1. Sensor packets

### BLE: one node's binary batch

Each notification contains a three-byte header (`<BBB`) followed by `count` samples. All multi-byte values are **little-endian**, with no padding. Each sample is 32 bytes, decoded in Python as `struct.Struct("<II6f")`.

| Byte offset | Field | Type / size | Meaning |
|---|---|---|---|
| 0 | `type` | uint8, 1 byte | `9` (`PacketType.SENSOR_BATCH`) |
| 1 | `count` | uint8, 1 byte | Number of samples; laptop accepts 1–5 |
| 2 | `source` | uint8, 1 byte | `0` = stream, `1` = dummy; applies to the entire batch |
| 3 onward | `samples` | `count × 32` bytes | Consecutive samples in the layout below |

Offsets below are relative to the start of **each sample**:

| Byte offset | Field | Type / size | Meaning |
|---|---|---|---|
| 0 | `sequence` | uint32, 4 bytes | Node's sample counter, starting at 1 and shared by all modes; never overridden by the laptop. |
| 4 | `timestamp` | uint32, 4 bytes | FireBeetle `millis()`: milliseconds since boot |
| 8, 12, 16 | `accel[0..2]` | Three float32 values, 12 bytes | Acceleration on x, y, z |
| 20, 24, 28 | `gyro[0..2]` | Three float32 values, 12 bytes | Angular velocity on x, y, z |

Payload size = `3 + 32 × count`: **163 bytes** for five samples. Node identity
comes from the BLE connection, not the payload. Both nodes and the laptop decoder
must use this three-byte-header format. Each batch contains one source.
Acquisition targets 200 Hz; motion-selected transmission need not be continuous
while the sensors are idle. The relay preserves the sensor values and axes; units,
mounting and calibration must match the hardware and model submissions.

### Laptop: decoded sample (internal dictionary)

Before pairing, `BLESensorNode` creates the following fields. This dictionary is internal to the laptop, not the MQTT payload.

| Field | Type | Meaning |
|---|---|---|
| `type` | integer | `10` |
| `node` | string | `"forearm"` or `"paddle"` |
| `source` | string | `"stream"` or `"dummy"`, copied from the batch header source byte |
| `sequence` | integer | Original per-node sample sequence |
| `raw_timestamp` | number | Original FireBeetle timestamp in ms |
| `clock_offset_ms` | number | Estimated node clock minus laptop monotonic clock |
| `common_timestamp` | number | `raw_timestamp - clock_offset_ms`, in laptop monotonic ms |
| `acceleration` | object | Numeric `x`, `y`, `z` acceleration values |
| `gyroscope` | object | Numeric `x`, `y`, `z` angular-velocity values |

### MQTT: one paired forearm + paddle sample

```json
{
  "type": 10,
  "source": "stream",
  "sensor_seq": 42,
  "session_id": "laptop-session-example",
  "timestamp": 12345678,
  "forearm_seq": 45,
  "paddle_seq": 44,
  "forearm": {
    "acceleration": {"x": 1.0, "y": 0.5, "z": 9.8},
    "gyroscope": {"x": 0.0, "y": 0.0, "z": 0.0}
  },
  "paddle": {
    "acceleration": {"x": 1.0, "y": 0.5, "z": 9.8},
    "gyroscope": {"x": 0.0, "y": 0.0, "z": 0.0}
  }
}
```

| Field | Type | Meaning |
|---|---|---|
| `type` | integer | `10` (`PacketType.SENSOR_DATA`) |
| `source` | string | Source shared by both paired samples: `"stream"` or `"dummy"` |
| `sensor_seq` | integer | Laptop's paired-sample counter, starting at 1 |
| `session_id` | string | Laptop pairing session identifier; generated as UUID hex |
| `timestamp` | integer | Earlier of the two corrected sample timestamps, rounded to integer laptop monotonic ms |
| `forearm_seq` | integer | Original forearm sample sequence |
| `paddle_seq` | integer | Original paddle sample sequence |
| `forearm`, `paddle` | object | Each contains `acceleration` and `gyroscope`, each with numeric `x`, `y`, `z` fields |

Samples pair by corrected acquisition time within 2.5 ms. Matching pairs publish
immediately. When a partner buffer is empty, samples can wait up to 1,000 ms for
delayed delivery; expiration or buffer capacity pressure emits singles with the
missing sensor and its sequence set to `null`. Timestamp-incompatible samples
can also emit as singles immediately. Older arrivals cannot move published
source timestamps backwards. The DPU requires complete pairs. Raw timestamps
and clock offsets are not included in the MQTT payload.

## 2. Result packet

```json
{
  "type": 11,
  "source": "stream",
  "timestamp": 98765432,
  "session_id": "ultra96-session-example",
  "sensor_session_id": "laptop-session-example",
  "result_seq": 7,
  "sensor_seq": 42,
  "stroke": "forehand",
  "confidence": 0.92,
  "sensor_sample_counts": {"forearm": 400, "paddle": 400},
  "complete_pairs": 400
}
```

| Field | Type | Meaning |
|---|---|---|
| `type` | integer | `11` (`PacketType.AI_RESULTS`) |
| `source` | string | Source of this inference window: `"stream"` or `"dummy"` |
| `timestamp` | integer | Ultra96 monotonic ms when the result is created |
| `session_id` | string | Ultra96 process session, generated as UUID hex |
| `sensor_session_id` | string | Laptop session that produced the input pairs |
| `result_seq` | integer | Result counter within the Ultra96 session, starting at 1 |
| `sensor_seq` | integer | Last input pair's ID; use with `sensor_session_id` to trace the source |
| `stroke` | string | Predicted stroke label |
| `confidence` | number | Confidence represented as a fraction, e.g. `0.92` means 92% |
| `sensor_sample_counts` | object | Actual sample counts for `forearm` and `paddle` in the window |
| `complete_pairs` | integer | Number of input packets containing both sensors |

The last `sensor_seq` plus `sensor_session_id` retain compact input correlation, while `session_id` plus `result_seq` identify the result.

The final DPU labels are `forehand`, `backhand`, `overhead`, `underhand`, `forehand_volley`, and `backhand_volley`.

## 3. Haptic packets

### MQTT command

```json
{
  "type": 12,
  "timestamp": 98765432,
  "session_id": "ultra96-session-example",
  "sensor_session_id": "laptop-session-example",
  "haptic_seq": 1,
  "result_seq": 10,
  "sensor_seq": 2000,
  "pattern": "double"
}
```

| Field | Type | Meaning |
|---|---|---|
| `type` | integer | `12` (`PacketType.HAPTIC_CMD`) |
| `timestamp` | integer | Ultra96 monotonic ms when the command is created |
| `session_id` | string | Ultra96 process session |
| `sensor_session_id` | string | Originating laptop sensor session |
| `haptic_seq` | integer | Haptic command counter within the Ultra96 session, starting at 1 |
| `result_seq` | integer | Result that triggered this command |
| `sensor_seq` | integer | Last input pair used by that result |
| `pattern` | string | Requested vibration pattern; currently `"double"` |

The DPU consumer emits a haptic command for each successfully published non-dummy AI result. Dummy results do not trigger haptics. The laptop applies the forwarding cooldown described below.

### BLE command and response

The laptop forwards only these fields to the **forearm** node, stripping both session fields to reduce payload size:

```json
{"type":12,"timestamp":98765432,"haptic_seq":1,"result_seq":10,"sensor_seq":2000,"pattern":"double"}
```

The laptop enforces a 2-second minimum interval between successful BLE haptic writes and keeps only the newest pending command during that wait. Sensor streaming and inference continue. The forearm firmware accepts supported patterns and acknowledges acceptance with:

```json
{"type":13,"status":"OK"}
```

`type` is `PacketType.HAPTIC_RESP`; `status` acknowledges acceptance for playback, not measured motor vibration. The response contains no sequence/session fields for matching acknowledgements to individual commands, and is logged on the laptop rather than relayed over MQTT.

## 4. Stream configuration

Activate the Python environment before starting the relay:

```sh
source comms/.venv/bin/activate
python comms/laptop/run_pipeline.py --mode stream
```

The laptop configures each node using JSON `{"type":3,"continuous":true}` and
performs the clock handshake before reception. `SYNC_END` (`8`) finishes clock
synchronisation. The acquisition rate is controlled by firmware, not sent by the
laptop. Sensor reception follows the same binary decoder and MQTT publisher
throughout the live session.

## 5. Mapping hex bytes to readable fields

Example of a one-sample packet (the decoder supports 1–5; normal firmware sends five):

```text
09 01 00 01 00 00 00 e8 03 00 00 00 00 80 3f 00 00 00 3f cd cc 1c 41 00 00 00 00 00 00 00 00 00 00 00 00
```

| Bytes | Meaning |
|---|---|
| `09` | Type 9, `SENSOR_BATCH` |
| `01` | One sample |
| Third byte `00` | Batch source = stream (`01` would mean dummy) |
| `01 00 00 00` | Little-endian sequence = 1 |
| `e8 03 00 00` | Little-endian timestamp = 1000 ms |
| `00 00 80 3f` | IEEE-754 float32 acceleration x = 1.0 |
| `00 00 00 3f` | Acceleration y = 0.5 |
| `cd cc 1c 41` | Acceleration z ≈ 9.8 |
| Three groups of `00 00 00 00` | Gyroscope x, y, z = 0.0 |

The BLE payload stays binary on the wire. `BLESensorNode` decodes it before writing human-readable DEBUG entries to the laptop log; no separate hex-inspection command is needed. For the example above, the message bodies are:

```text
[SENSOR RX] type=SENSOR_BATCH (0x09) source=stream count=1 bytes=35
[SENSOR RX] source=stream sequence=1 timestamp_ms=1000 acceleration=(x=1, y=0.5, z=9.8) gyroscope=(x=0, y=0, z=0)
```

The logger adds timestamp and node (`FOREARM` or `PADDLE`). Each batch has a type/count/length summary followed by its decoded samples. Invalid counts or lengths are logged and the batch is not enqueued. Logs always include DEBUG records; `-v` only also displays them in the terminal. Paired MQTT publishing additionally logs the paired sequence and both original node sequences as `[SENSOR TX]`.

Hex is just a representation of bytes: readings are decoded as float32, not converted directly from hex to integers. This binary format applies to BLE sensor batches. Existing BLE control commands and MQTT payloads remain JSON text.

## Clock and sequence rules

- All timestamps here are in **milliseconds**, but their clocks differ. FireBeetle uses time since boot; laptop and Ultra96 use their own monotonic clocks. They are not Unix/UTC timestamps.
- FireBeetle timestamps are uint32 and wrap after roughly 49.7 days. The current decode path directly applies the clock offset without rollover unwrapping.
- Identify a sensor pair by `(sensor_session_id, sensor_seq)` when reading results, or `(session_id, sensor_seq)` on sensor packets. Identify results/haptics by their Ultra96 `session_id` plus their respective sequence counters.
- QoS 0 sensor delivery can lose messages. QoS 1 result and haptic delivery can include duplicates; sequence/session fields provide correlation, but not every consumer currently deduplicates them.

## Latency diagnostics

Laptop logs periodic round-trip times (RTT); no clocks on different devices are subtracted.

- BLE forearm/paddle: ordinary JSON `{"type":6,"request_id":1000001}` produces `{"type":7,"request_id":1000001,"node_timestamp":12345}`. RTT uses local send/receive times; the remote timestamp is not used for the latency calculation. This probe does not send SYNC_START/SYNC_END or alter clock offsets.
- MQTT: laptop sends `{"id":"laptop-run-id","origin":"laptop","target":"ultra96","sent_ns":123456789000}` on `latency/ultra96/req`; Ultra96 echoes it on `latency/laptop/resp`. `target` can also be `phone` or `laptop` (broker loopback). All diagnostics use QoS 0 and do not enter the sensor/inference pipeline.
- Each route is probed approximately every 10 seconds. BLE response timeout is one second; MQTT simply logs a returned timestamp echo; missing replies produce no RTT line. `sent_ns` is laptop monotonic nanoseconds; the laptop computes `(now_ns - sent_ns) / 1e6`. The per-run ID rejects replies from earlier runs; duplicate echoes are not tracked. The phone must run the updated Unity script. RTT includes transport, broker routing where applicable, and response scheduling; it excludes inference and screen rendering.

Both Python processes retry broker connections in the background, including when it is absent at startup. Live publishes attempted while disconnected are dropped. Existing MQTT QoS 1 in-flight messages can still be redelivered on reconnect.

## Readable packet types in logs

`packet_type_name()` in `utilities/constants.py` uses the shared `PacketType(IntEnum)` members
to labels such as `SENSOR_BATCH (0x09)`, `AI_RESULTS (0x0B)` and `FILE_CHUNK (0x13)`.
Unknown integer codes produce `UNKNOWN (0xNN)`; invalid values have an explicit
invalid-type label. Add new packet types to `PacketType`; the log helper uses each member’s `.name`
and numeric value automatically.

`format_packet_for_log()` in `utilities/logger_setup.py` formats a copy of JSON
packet data with a readable `type`. It never changes the original packet or its
numeric wire encoding. BLE control RX/TX, binary sensor summaries and MQTT RX/TX
use these helpers.

```python
from utilities.constants import packet_type_name
from utilities.logger_setup import format_packet_for_log

packet_type_name(0x0B)  # 'AI_RESULTS (0x0B)'
format_packet_for_log({"type": 12, "pattern": "double"})
# '{"type": "HAPTIC_CMD (0x0C)", "pattern": "double"}'
```
