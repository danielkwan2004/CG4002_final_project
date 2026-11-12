# Communications layout

For local Mosquitto setup, TLS credentials, and a hardware-free smoke test, see
the [local broker setup guide](broker/README.md).

## Hardware-free sensor sender

With the MQTT broker and Ultra96 consumer running, start this on the laptop:

```sh
comms/.venv/bin/python comms/laptop/send_dummy_sensors.py --interval 2
```

This reuses `DummySensorNode` to generate 200 complete forearm/paddle pairs,
paced at 200 Hz over one second, with two seconds between capture starts.
It publishes the normal sensor schema to `fb/sensor/raw` with source `dummy`
and prints results received on `ultra96/ai/results`. No BLE or keyboard input
is needed. Stop with Ctrl-C. Use the existing laptop MQTT credentials in `.env`;
export `BROKER_HOST` and `CA_CERTS_PATH` before launch if overrides are needed.
Run this sender separately from the real laptop pipeline to avoid competing
sensor sessions. MQTT uses QoS 0, so network loss can reduce received counts.

`ultra96_comms.py` produces simulated random results. For actual DPU execution,
use `ultra96_comms_dpu.py` with its local DPU server running; it consumes 200
complete pairs per inference. Random sensor values test the inference plumbing,
not stroke recognition accuracy. Dummy inputs do not trigger haptics.

See the [packet reference](PACKET_REFERENCE.md) for sensor, result, haptic and
dummy packet structures, field meanings, transport routes and examples.

- `utilities/`: shared packet constants, logging and MQTT wrapper.
- `laptop/`: BLE relay, synchroniser, file receiver and simulation scripts.
- `ultra96/`: AI-result and haptic service.
- `firebeetle/`: Arduino sketches, each kept inside its matching sketch directory.
- `unity-phone/`: Unity visualiser.
- `broker/`: broker configuration and certificates.

Run from the repository root (with the communications dependencies installed):

```sh
python comms/laptop/run_pipeline.py --mode stream
python comms/laptop/run_pipeline.py --mode keyboard
python comms/laptop/run_pipeline.py --mode both
python comms/laptop/ble_file_transfer.py
python comms/ultra96/ultra96_comms.py
```

Direct execution from inside the laptop/Ultra96 directories also works.
The small `_bootstrap.py` modules expose the sibling utilities package.
Logs are stored under `comms/logs/`, independent of the working directory:
Ultra96 writes directly to `comms/logs/`. The laptop and simulators use
`laptop/`, `sim_phone/`, and `sim_ultra96/` subdirectories respectively.
Direct calls to `get_logger()` without a directory override also use
`comms/logs/` itself. Directories are created automatically.
Existing logs in older locations are not moved or deleted. Full DEBUG detail
is always saved to files; `-v` controls whether it also appears in the terminal.

For this logging update on Ultra96, copy `utilities/logger_setup.py` and
`ultra96/ultra96_comms.py`, preserving their sibling directory layout.
For example, a deployment at `/comms/` writes Ultra96 logs to
`/comms/logs/`. The account running Python needs write access there.

For Ultra96 deployment, copy both `ultra96/` and `utilities/`, retaining
their sibling layout. Keep credentials in the existing environment or `.env`.
Set machine-specific broker and CA paths as exported environment variables:

```sh
export BROKER_HOST=localhost
export CA_CERTS_PATH=/absolute/path/to/ca.crt
python comms/ultra96/ultra96_comms.py
```

These two overrides must be set before starting Python. Their defaults are
the laptop hostname and `comms/broker/certs/ca.crt`, resolved from the shared
module location rather than the current working directory. These must be set 
each time you access the Ultra96. Do not copy private broker keys to Ultra96; 
only its trusted CA certificate is needed.

Alternatively, change these manually in the `constants.py` file:
```sh
BROKER_HOST = "localhost"
CA_CERTS_PATH = "absolute/path/to/ca.crt"
```

All three modes use the same binary BLE sensor format, decoder, timestamp
pairing and `fb/sensor/raw` MQTT topic. Each keyboard press requests one second
of sampling at 200 Hz. In `both` mode this runs alongside continuous sampling,
so the combined rate is about 400 Hz during that second. Ultra96 collects
stream and dummy pairs separately into one-second **acquisition-time** windows,
using the paired packet's `timestamp`. Each dummy burst starts at its first
available pair. Stream windows remain contiguous. Ultra96 uses no extra allowance for delivery of samples acquired within that same second; this does not
increase the acquisition duration. A late tail cannot reopen a closed window.
There is no strict sample-count requirement, and dummy results do not trigger
haptics. This collector uses the existing source/timestamp payload and does not
require capture IDs, end markers, or new firmware.

Each FireBeetle fixes its sampling interval at 5 ms (200 Hz). The laptop
configures only continuous versus keyboard-only mode, not the sample rate.
Continuous and keyboard schedules always stack in `both` mode; there is no
pause-during-keypress setting. Clock synchronisation still briefly pauses
sampling as before; latency probes do not request a pause.

Binary sensor packets are decoded directly into laptop log entries showing
packet type, source, sequence, timestamp, acceleration and gyroscope readings.
A logging worker writes file/console output so callbacks do not wait for disk I/O.
File logs always contain these DEBUG entries; `-v` also shows them on screen.
Control commands and MQTT payloads retain their existing JSON formats.

Deploy the updated `FireBeetle_BLE` sketch to **both** nodes (set `NODE_ID`
appropriately), and update laptop plus Ultra96 code together. Sensor batches contain
163 bytes for five samples (including source in the three-byte header), with no application-level CRC trailer. Update both
FireBeetles and the laptop together when switching from either the old untagged or per-sample-tagged format. Update Ultra96 as well, and rebuild
the Unity app for the latest-reading sensor display (without a per-sample UI backlog). The old dummy relay topic is no longer used.
`-k` still selects keyboard mode; `--packets-per-key` has been removed.

Offline protocol/scheduler checks (no broker or BLE hardware needed):

```sh
python3 -m unittest discover -s comms/tests -v
```

## Broker availability and latency

The laptop and Ultra96 may start before the broker. MQTT connects in the
background and retries indefinitely with exponential backoff capped at 15 seconds.
Subscriptions are restored after reconnects. New sensor/results/haptic publishes
while disconnected are dropped, not accumulated for later playback. Already
in-flight QoS 1 messages may still be redelivered by MQTT. BLE sampling continues
while the broker is down. Local configuration errors (for example a missing CA
file) still need to be fixed before starting.

The laptop records `[LATENCY]` checks at DEBUG level approximately every 10 seconds.
They remain in the log files; use `-v` to show them in the terminal:

| Route | What is timed |
|---|---|
| Laptop ↔ forearm / paddle | BLE write plus notification response, using SYNC_REQ/SYNC_RESP without pausing or updating clocks |
| Laptop ↔ broker loopback | MQTT publish back to the laptop, then its echo reply |
| Laptop ↔ Ultra96 | Request/reply via the broker |
| Laptop ↔ phone | Request/reply via the broker and Unity MQTT callback |

These are round-trip times measured on the laptop's monotonic clock, not one-way
latencies, inference time, vibration completion, or phone rendering time. BLE
response waits time out after one second. MQTT uses simple timestamp echoes;
a missing echo produces no RTT line.
An offline device is reported as unavailable/no reply rather than assigned a latency.
The broker loopback includes two MQTT deliveries through the broker because the
laptop uses the same echo mechanism as the remote devices.

MQTT diagnostics use `latency/{device}/req` and
`latency/laptop/resp`, QoS 0. Device names are `laptop`, `ultra96`, `phone`.
Python topic templates are defined in `utilities/constants.py`; Unity keeps matching
constants in `PickleVizMqttClient.cs`.
The current broker config has no topic ACL; if you add ACLs, allow these topics.
Rebuild/install the Unity app from `Assets/Scripts/PickleVizMqttClient.cs` for phone
replies. `sim_phone.py` and `sim_ultra96.py` have not been changed.

Results keep `sensor_session_id` and the last `sensor_seq` for tracing input across
laptop restarts, plus the Ultra96 `session_id`/`result_seq` to identify the result.
The long `sensor_seqs` list has been removed; `complete_pairs` gives the paired count and `sensor_sample_counts` gives counts per board.

## Checking capture delay

For the timestamp-window change, copy only `ultra96/ultra96_comms.py` to Ultra96
and restart it. Keep the running laptop/firmware packet format unchanged.

The scheduling lead is 200 ms, acquisition is one second, and the collector
uses no extra delivery allowance. Expect roughly 1.3–1.5 seconds under normal
transport conditions, with fewer pairs when delivery falls behind.
`WINDOW_DELIVERY_GRACE_SECONDS` in the Ultra96 script controls the allowance.
Reducing it reduces waiting but risks discarding late pairs. Samples arriving
after a window closes are logged at DEBUG and cannot produce a second result.
This relies on the existing one-second, non-overlapping keyboard captures and
monotonically increasing corrected sample timestamps; a laptop session change
resets the collector.

Keep `SAMPLE_INTERVAL_MS = 5` (200 Hz per source). Faster sampling increases BLE
load and does not recover lost pairs. `sensor_sample_counts` reports the actual data,
without padding or duplicating readings. The classifier is still simulated;
a future fixed-shape model would need its own resampling/input preparation.

Regression checks, including replay of the copied Ultra96 log when available:

```sh
python3 -m unittest discover -s comms/tests -p test_acquisition_windows.py -v
```

## BLE setup recovery

Update `laptop/ble_sensor_node.py` and `laptop/run_pipeline.py`, then restart the
pipeline. Setup uses one shared lock for discovery through clock synchronisation;
the two established streams still run concurrently. Bleak receives the discovered
BLEDevice instead of an address (which would initiate another discovery).
Connection errors now identify their stage. Failed initial clock sync never marks
a node ready, and setup tasks are cancelled during disconnect.

Reflash **both** boards using `FireBeetle_BLE.ino`, setting `NODE_ID` to `forearm`
and `paddle` respectively. The sketch does not impose a second HELLO watchdog. The laptop owns
setup retries. The current user settings are 3 seconds for Bleak connection and
2 seconds for notification subscription, HELLO, configuration and clock sync.
The outer connect/service-discovery budget is 7 seconds (3 + 2 + 2), allowing
Bleak to run native timeout cleanup first instead of racing an identical timeout. Firmware logs disconnect reason
codes. It retains the running laptop's three-byte batch header (163 bytes for five
samples) and start-timestamp-only capture command. No capture-ID format is needed.
These are maximum attempt budgets, not mandatory startup waits. A failed attempt
is disconnected before retrying; the firmware cannot race an arriving HELLO with
its own independent timeout.

These changes address avoidable setup failures. Hardware tests are still required
to establish whether any controller, bonding, power or radio fault remains.

BLE clock synchronisation and latency now share `_request_sync_reply()` in
`ble_sensor_node.py`. A latency probe uses the normal write lock only while
sending; it does not hold the writer while waiting for the reply. Probes skip
active captures. MQTT latency remains a request ID echoed back to the sender,
with round-trip time measured entirely on the sender's monotonic clock. MQTT
probes include `sent_ns` and a per-run `id`; echoes from a previous run are ignored.
There is no pending-probe table, timeout sweep or duplicate-reply tracking.
A missing MQTT reply produces no RTT line; a duplicate echo can produce another
line. This is a diagnostic RTT measurement, not an inference or UI latency metric.

Every connection attempt scans for the board by name. If discovery fails, the
laptop can retry its last discovered device; otherwise it waits and scans again. A returned HELLO with a
wrong node ID is rejected. Connection cleanup is attempted even after a failed
connect, and the client reference is then cleared. Firmware checks advertising
startup success and retries once per second while disconnected if advertising
is inactive. Failed encryption or hardware/reset faults still require the board's
serial output to diagnose; bonds and encryption settings are not automatically
changed.


## Demo version and validation

Run `ultra96/ultra96_comms.py`. The older `ultra96_comms copy.py` is a historical
backup, not the demo entry point. It groups by arrival time and can turn a delayed
dummy tail into a second inference. The current script uses one-second acquisition
windows, separate source buffers, and zero additional delivery grace. Late pairs
are dropped rather than starting another result for that window; 200 pairs is a
sampling target, not a required result count.

The firmware currently supplies placeholder IMU values and Ultra96 chooses random
stroke/confidence values. These scripts demonstrate the communication pipeline.

Current regression checks (from the repository root):

```sh
comms/.venv/bin/python -m unittest discover -s comms/tests -p test_ble_setup.py
comms/.venv/bin/python -m unittest discover -s comms/tests -p test_mqtt_runtime.py
comms/.venv/bin/python -m unittest discover -s comms/tests -p test_acquisition_windows.py
```

The acquisition tests include the actual binary decoder and pairing code in all
three modes, a zero-grace late-tail check, and dummy/stream haptic separation.
Historical delivery-grace tests explicitly enable 0.6 seconds; production remains
at zero. Older `test_ble_sensor_node.py`, `test_sensor_pipeline.py`,
`test_firmware_scheduler.py`, and `sensor_helpers.py` still describe the retired
capture-ID/end-marker protocol and are not current regression checks.
Hardware delivery, phone rendering and intermittent BLE faults require an actual
device run.

### Operation with one FireBeetle

The synchroniser now enforces nondecreasing published timestamps separately for
`stream` and `dummy`. After newer data has been published, an older arriving sample
is dropped rather than sent backwards in time and resetting the Ultra96 DPU input
buffer. Stale samples are removed before pairing so they cannot consume a current
partner. Original timestamps are not rewritten. Existing pairing tolerance
(2.5 ms) and single-sensor wait (100 ms) are unchanged.

`[SYNC STATS]` includes `late_forearm` and `late_paddle`; individual drops appear
as `[SYNC LATE]` at DEBUG level. These late drops are separate from the existing
published-sample match-rate calculation and `received_*` counters. A low match
rate or high late count still requires investigation of firmware acquisition
timestamps, clock alignment, and buffered BLE delivery. This ordering safeguard
does not reconstruct two-sensor windows or make zero-filled model inputs valid.
Restart the laptop pipeline after updating `laptop/synchroniser.py`; no firmware
or Ultra96 change is needed for this safeguard.

Offline ordering regression checks:

```sh
comms/.venv/bin/python -m unittest discover -s comms/laptop -p test_synchroniser_ordering.py -v
```

The laptop synchroniser allows up to 100 ms (`pairing_timeout_ms`) for a
matching sample. If none arrives, it publishes the available sample with the
missing `forearm` or `paddle` and its corresponding sequence set to JSON `null`.
Timestamp-incompatible samples are also published individually. No synthetic
values are substituted. Pairing resumes automatically when matching samples
arrive again, preserving the MQTT session and increasing `sensor_seq`.
Keyboard captures target whichever boards are currently ready.

The Ultra96 service continues its one-second windows with single-sensor packets.
Results include `sensor_sample_counts` for each board and `complete_pairs`;
single-sensor packets contribute only to their available board’s sample count.
This service currently generates simulated stroke/confidence values. A trained
model integration must explicitly support missing sensor inputs before these
results can represent real single-sensor inference.

Synchroniser statistics use `single_forearm` and `single_paddle` for samples
published without a partner. The cumulative `match_rate_percent` is
`100 * (2 * matched) / (2 * matched + single_forearm + single_paddle)`:
the percentage of processed sensor samples included in complete pairs.
Pending buffered samples are excluded; an empty history reports 0%.


### Starting and stopping a live session

Stream and combined (`--mode both`) modes start with sensor publication paused.
Connect both boards, put on the strap and hold the paddle, then move both sensors
and press **Space** when ready. Start requires both BLE nodes to be ready and a
sample acquired within the last two seconds from each board. If Start is rejected,
move both sensors and press Space again.

Space starts a new session ID and resets pairing statistics. Samples captured
before Start are excluded, including delayed BLE batches. Press Space again to
stop publication and clear pending samples; BLE reception and diagnostic logging
continue. During an active session, missing sensor data still produces singles
under the normal pairing timeout; this gate does not fix firmware or BLE delays.

Keyboard-only mode retains its existing capture behavior. In combined mode,
Space controls the session and other printable keys request captures while active.
Use `--no-readiness-gate` for immediate publication or headless stream operation.
The default gate requires an interactive macOS/Linux terminal.
