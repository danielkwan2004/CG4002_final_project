# Sensor, result, haptic and dummy packet reference

Reference for the current `FireBeetle_BLE` → laptop → Ultra96 pipeline (30 September 2026). JSON examples use decimal packet IDs; hex IDs below refer to the same numbers. JSON field order does not matter. BLE sensor batches are binary; the other wire payloads described here are JSON.

## Quick lookup

| Packet | Type (hex / decimal) | Route | Transport / topic |
|---|---|---|---|
| Sensor batch | `0x09` / `9` | Each FireBeetle → laptop | BLE notification, binary |
| Paired sensor data | `0x0A` / `10` | Laptop → Ultra96 | MQTT `fb/sensor/raw`, QoS 0 |
| AI result | `0x0B` / `11` | Ultra96 → result subscribers | MQTT `ultra96/ai/results`, QoS 1 |
| Haptic command | `0x0C` / `12` | Ultra96 → laptop → forearm FireBeetle | MQTT `ultra96/ai/haptics`, QoS 1, then BLE write |
| Haptic response | `0x0D` / `13` | Forearm FireBeetle → laptop | BLE notification |
| Dummy trigger | `0x0E` / `14` | Laptop → both FireBeetles | BLE write |

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

Payload size = `3 + 32 × count`: **163 bytes** for five samples in every mode. Continuous sampling and the one-second keyboard burst each run at 200 Hz (5 ms/sample) and call the same sample builder. Either alone nominally emits 40 five-sample notifications/second; together they emit about 80. A short final batch is flushed when the keyboard burst ends (including in combined mode), so a delayed loop does not leave samples unsent. Node identity comes from the BLE connection, not the payload. Separate source batches may be delivered out of global sample-sequence order; timestamps and source govern pairing, and each source retains its own sample order.

Each batch contains exactly one source, using separate normal and dummy firmware buffers. The laptop copies the header source onto every decoded sample. There is no application-level CRC field or check. The laptop validates packet type, count and length before decoding. Update both nodes and the laptop together when moving from the old untagged format. The experimental seven-byte capture-ID header is not used. Keep both nodes and the laptop on this three-byte-header format.

**Units / axes:** this sketch currently sends fixed acceleration `[1.0, 0.5, 9.8]` and gyro `[0.0, 0.0, 0.0]`. It does not establish real sensor units or mounting-axis conventions. Agree on these during hardware integration; do not assume the gyro values are degrees/s or radians/s from this schema alone.

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

All modes pair samples by corrected time with a default 2.5 ms tolerance, using independent forearm/paddle buffers for each source. A stream sample is never paired with a dummy sample. The three sequence values need not match: unmatched samples can be dropped. Raw node timestamps and clock offsets are not included in this MQTT packet.

## 2. Result packet

```json
{
  "type": 11,
  "source": "dummy",
  "timestamp": 98765432,
  "session_id": "ultra96-session-example",
  "sensor_session_id": "laptop-session-example",
  "result_seq": 7,
  "sensor_seq": 42,
  "stroke": "forehand",
  "confidence": 0.92,
  "sensor_sample_counts": {"forearm": 3, "paddle": 3},
  "complete_pairs": 3
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

The long `sensor_seqs` array is removed. The last `sensor_seq` plus `sensor_session_id` retain compact input correlation, while `session_id` plus `result_seq` identify the result.

Current labels: `forehand`, `backhand`, `overhead stroke`, `overhead smash`, `underhand short arch`, `underhand long arch`.

The current Ultra96 service **simulates inference** by choosing a random stroke and confidence between 0.75 and 0.99. Both sources now use one-second acquisition-time windows based on the paired packet's `timestamp`, rather than elapsed MQTT receive time. Stream windows are contiguous; the first available dummy pair anchors each non-overlapping one-second keyboard capture. Neither path requires exactly 200 pairs.

Ultra96 now uses **zero extra delivery allowance**, prioritising response time. At the acquisition-window delivery deadline it publishes one result using the pairs already received. Pairs arriving after the deadline are dropped; no second dummy inference is created. A laptop session change clears pending windows. The collector accepts the existing source/timestamp packets and does not require capture IDs or end markers.

The Unity UI displays the result JSON, including `source="dummy"`, `sensor_sample_counts`, and `complete_pairs`. Dummy results never trigger haptics or increment the stream-result haptic counter. Sensor display updates use the latest received reading rather than queueing every sample for rendering.

The current communications service accepts variable window sizes. When replacing the simulated classifier with a real model, its input preparation must also support the variable number of pairs or resample them to the model's required shape.

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
| `pattern` | string | Requested vibration pattern; currently `"double_pulse"` |

The service emits a command after at least 10 normal results since the previous command and at least 10 seconds between commands. This currently tests the feedback path; it is not based on stroke quality.

### BLE command and response

The laptop forwards only these fields to the **forearm** node, stripping both session fields to reduce payload size:

```json
{"type":12,"timestamp":98765432,"haptic_seq":1,"result_seq":10,"sensor_seq":2000,"pattern":"double_pulse"}
```

The laptop also enforces a 10-second cooldown and keeps only the newest queued command. The firmware reads `pattern`, logs it, and replies:

```json
{"type":13,"status":"OK"}
```

`type` is `PacketType.HAPTIC_RESP`; `status` acknowledges handling the command. **Actuator control is still a TODO**, so this does not prove a vibration occurred. The response contains no sequence/session fields for matching acknowledgements to individual commands, and is logged on the laptop rather than relayed over MQTT.

## 4. Three modes, one sensor pipeline

```sh
python comms/laptop/run_pipeline.py --mode stream
python comms/laptop/run_pipeline.py --mode keyboard
python comms/laptop/run_pipeline.py --mode both
```

Default is `both`; `-k` remains an alias for `--mode keyboard`. The old `--packets-per-key` option is removed: a capture requests one second of sampling at 200 Hz.

| Mode | Sampling behaviour | Keypress behaviour |
|---|---|---|
| `stream` | Continuous 200 Hz | No keyboard listener |
| `keyboard` | Idle between bursts | Sample at 200 Hz for one second, then stop |
| `both` | Continuous 200 Hz | Add a second 200 Hz schedule for one second: about 400 samples/second total |

Combined mode currently **does not pause streaming**. Both schedules call `appendSensorSample()`, share the same sequence counter and batch-building function, and feed the same laptop queues, synchroniser and MQTT publisher. Both use the same packet type, with a source flag in the batch header and separate buffers for the two sources. Pairing requires matching source plus timestamp proximity; Ultra96 buffers the two sources independently. Both sources currently use the same placeholder readings.

Both schedules always stack in combined mode. The optional pause-during-capture flag has been removed. Normal clock resynchronisation remains separate and still uses its existing short pause; periodic latency probes reuse a single SYNC_REQ without that pause.

Every mode follows:

```text
FireBeetle continuous / keyboard 200 Hz schedules → shared sample builder
  → five-sample BLE batch (0x09)
  → laptop layout validation and clock correction
  → forearm/paddle pairing by source + timestamp
  → paired JSON (0x0A) on fb/sensor/raw
  → separate stream/dummy acquisition windows + delivery allowance → tagged results
  → haptic policy for normal results only
```

### Configuration

The laptop's existing CONFIG packet now includes the sampling mode:

```json
{"type":3,"continuous":false}
```

`continuous` is false for keyboard-only mode and true for stream/both. The firmware fixes each schedule at 200 Hz (`SAMPLE_INTERVAL_MS = 5`); sample rate is no longer sent by the laptop. SYNC_END (`8`) completes clock synchronisation in all modes; with `continuous=false`, sampling remains idle until a capture request.

### Minimal capture request

The laptop writes this JSON to both nodes:

```json
{"type":14,"start_timestamp":12345678}
```

| Field | Type | Meaning |
|---|---|---|
| `type` | integer | `14` (`PacketType.DUMMY`), now a capture trigger only |
| `start_timestamp` | uint32 integer | Planned start in the receiving node's `millis()` clock |

The laptop chooses a common start about 200 ms ahead and translates it with each node's clock offset, so the numeric timestamp can differ between nodes. This field is necessary to coordinate two separate BLE writes. Firmware rejects a start already in the past or more than two seconds ahead. The keyboard schedule starts at that time and ends 1000 ms later, independent of the continuous schedule. A delayed loop can collect fewer than 200 samples; the burst still ends on time.

Both nodes send the ordinary three-byte-header sensor batch layout with their own sequence counters. There are no capture IDs or end markers in the active format. A successful BLE write alone does not guarantee a complete capture. Keys during the approximately 1.3-second guard are ignored. An explicit sync pause or disconnect cancels firmware capture.

`dummy_sensor_node.py` is a separate unused local fake source. It does not implement capture IDs/end markers and is not a substitute for the current BLE keyboard pipeline.

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

- All timestamps here are in **milliseconds**, but their clocks differ. FireBeetle uses time since boot; laptop and Ultra96 use their own monotonic clocks. They are not Unix/UTC timestamps. Do not subtract an Ultra96 result timestamp from a laptop sensor timestamp to calculate latency without an additional clock mapping.
- FireBeetle timestamps are uint32 and wrap after roughly 49.7 days. The current decode path directly applies the clock offset without rollover unwrapping.
- Identify a sensor pair by `(sensor_session_id, sensor_seq)` when reading results, or `(session_id, sensor_seq)` on sensor packets. Identify results/haptics by their Ultra96 `session_id` plus their respective sequence counters.
- QoS 0 sensor delivery can lose messages. QoS 1 result and haptic delivery can include duplicates; sequence/session fields provide correlation, but not every consumer currently deduplicates them.

## Source of truth

- [Packet IDs, topics and defaults](utilities/constants.py)
- [BLE binary layouts, sample generation and acknowledgements](firebeetle/FireBeetle_BLE/FireBeetle_BLE.ino)
- [BLE decoding, clock correction and dummy triggers](laptop/ble_sensor_node.py)
- [Paired sensor packet builder](laptop/synchroniser.py)
- [MQTT publishing, capture triggers and haptic forwarding](laptop/run_pipeline.py)
- [Result and haptic creation](ultra96/ultra96_comms.py)
- [Local dummy sensor source](laptop/dummy_sensor_node.py)

- [Binary sensor decoder and layout validation](laptop/ble_sensor_node.py)

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
numeric wire encoding. BLE control RX/TX, binary sensor summaries, MQTT RX/TX and
file-transfer logs use these helpers. The file-transfer script now writes its
packet DEBUG log to `comms/logs/ble_file_transfer_*.log`.

```python
from utilities.constants import packet_type_name
from utilities.logger_setup import format_packet_for_log

packet_type_name(0x0B)  # 'AI_RESULTS (0x0B)'
format_packet_for_log({"type": 12, "pattern": "double_pulse"})
# '{"type": "HAPTIC_CMD (0x0C)", "pattern": "double_pulse"}'
```

Existing log files are not rewritten; new runs use the readable names.

Python producers and consumers now use `PacketType.SENSOR_DATA`,
`PacketType.AI_RESULTS`, etc. Members compare equal to their wire integers and
JSON serialises them as numbers. The Arduino enums and binary layouts are
unchanged. Two compatibility aliases remain solely for `sim_ultra96.py`, which
has not been edited.

## Connection and latency fixes (30 September)

- The laptop serialises initial BLE discovery/setup and passes the discovered device to Bleak, avoiding a second implicit scan. Each node must have a valid clock before it is marked ready; failed initial sync is retried, then setup reconnects.
- The firmware HELLO watchdog is removed. The laptop owns setup deadlines: the configured native connection timeout is 3 seconds and subscription/HELLO/configuration/clock sync gets 2 seconds. An outer 7-second connect/service-discovery limit leaves room for native timeout cleanup. Firmware requests a four-second link supervision timeout and logs disconnect reasons. RF/OS failures still require hardware diagnosis.
- Capture scheduling uses a 200 ms lead plus one second of acquisition, so expect at least about 1.2 seconds from keypress, plus transport and processing. Compare the laptop `Capture key handled` log with the Ultra96 result timestamp after accounting for timezone and clock offset. The laptop does not currently subscribe to AI results.
- BLE latency probes reuse SYNC_REQ without pausing sampling. Human-readable packet logs are written on a separate logging thread. Use the regular console mode for timing checks; `-v` prints every decoded packet.
- Reflash **both** boards with distinct `NODE_ID` values, update laptop and Ultra96 code together, and rebuild the phone app for the display-path improvement. Keep `BROKER_HOST=localhost` on Ultra96 when using the existing reverse SSH tunnel.
