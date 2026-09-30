# Sensor Node Hand-off Interface (Phase F)

Transport update, 2026-09-30: v4 batching delivered all 7,312 movement samples
across the 21:01/21:03 captures with zero send errors or loss. The current
`staggered_v1` revision additionally spreads diagnostics across sampling slots
to address periodic jitter; physical validation of that scheduling change is
pending. Sensor fields and units below are unchanged. See
[TRANSPORT_RELIABILITY_TEST_GUIDE.md](TRANSPORT_RELIABILITY_TEST_GUIDE.md)
for the current wire framing, pending/final accounting, and capture scope. Any v3
immediate-send descriptions below refer to the earlier bring-up revision.

Updated for P1/P2 diagnostics, 2026-09-29. The selected gyro range/conversion is now
aligned in source and verified in the later hardware captures. Earlier captures
used the mismatched configuration and must not be relabeled as corrected data.

Audience: the Comms teammate building BLE/GATT + the SENSOR_DATA / HAPTIC_CMD packet
framing from `CG4002_Design_Report.md` Section 4.2.3. This document describes the real
field names, units, and ranges produced by the current firmware
(`CG4002_hardware.ino`, `SensorFrame.h`). It is not a transport protocol — no BLE/MQTT
code is included here.

## 1. `SensorFrame` field reference (`SensorFrame.h`)

| Field | Type | Units / meaning | Notes |
|---|---|---|---|
| `timestamp_us` | `unsigned long` | microseconds since boot (`micros()`) | 32-bit, wraps at ~71 min uptime; relative timing only, not wall-clock |
| `interval_us` | `unsigned long` | interval since previous completed IMU read | first production sample is 0; unsigned wrap-safe; populated by acquisition diagnostics |
| `node_id` | `uint8_t` | node identity | `1` = forearm node (current firmware). Paddle node ID is not yet assigned (Phase J) |
| `seq` | `uint32_t` | per-node monotonic sample counter | starts at 0 on boot, increments every produced sample |
| `ax`, `ay`, `az` | `int16_t` | raw accelerometer counts, axis-mapped | two's complement; scale is 2048 LSB/g at the configured ±16g range |
| `gx`, `gy`, `gz` | `int16_t` | raw gyroscope counts, axis-mapped | two's complement; scale is 16.4 LSB/dps at the configured ±2000dps range |
| `ax_g`, `ay_g`, `az_g` | `float` | accelerometer, g | axis-mapped **and** offset-calibrated (stationary bias subtracted); **not** low-pass filtered |
| `gx_dps`, `gy_dps`, `gz_dps` | `float` | gyroscope, deg/s | axis-mapped physical-unit conversion only; **not** bias-corrected, **not** filtered |
| `ax_filtered_g`, `ay_filtered_g`, `az_filtered_g` | `float` | accelerometer, g | offset-calibrated **and** low-pass filtered (`FILTER_ALPHA=0.2`) |
| `gx_filtered_dps`, `gy_filtered_dps`, `gz_filtered_dps` | `float` | gyroscope, deg/s | bias-corrected **and** low-pass filtered (`FILTER_ALPHA=0.2`) |
| `status_flags` | `uint8_t` | bitfield, see below | |

**Important asymmetry**: for gyro, only the `*_filtered_dps` fields have bias correction
applied — `gx_dps`/`gy_dps`/`gz_dps` are raw physical-unit conversions. For accel, bias
correction is applied before buffering, so both `ax_g`/`ay_g`/`az_g` and the filtered
fields are calibrated; only the filtered fields additionally have smoothing applied.

Target sample rate: 200 Hz (`SAMPLE_PERIOD_US = 5000` in `ImuConfig.h`). Achieved
cadence must be established from the new timing capture. Timestamps describe
completed register reads, not a sensor data-ready timestamp.

## 2. `status_flags` bitfield (`SensorFrame.h`)

| Bit | Constant | Meaning |
|---|---|---|
| `0x01` | `SENSOR_STATUS_SATURATED` | at least one raw axis (accel or gyro) is within 90% of its full-scale range |
| `0x02` | `SENSOR_STATUS_PHYSICAL_UNITS_VALID` | the IMU driver successfully converted raw counts to g/dps this sample |
| `0x04` | `SENSOR_STATUS_CALIBRATED` | the consumer stage (gyro bias correction + filtering) completed for this sample |
| `0x08` | `SENSOR_STATUS_MOVE_ACTIVE` | frame belongs to a transmitted movement burst, including its final boundary sample |

Bits are OR'd together. Normal idle processed samples carry `0x06`; they are not
transmitted as full sample packets. Normal movement frames carry `0x0E` (14).
Saturation adds `0x01`, giving `0x07` while idle or `0x0F` (15) in a movement burst.
A frame missing `0x02` or `0x04` indicates a partially-processed or
faulted sample and should be treated with suspicion by downstream consumers.

## 3. Node lifecycle state (not currently in `SensorFrame`)

The firmware tracks a separate node state machine (`BOOT -> CALIBRATING -> STREAMING ->
FAULT`), logged to Serial as `[state] <NAME>` but not yet included in the packet
contract. If Comms' HELLO packet (Section 4.2.3) needs this, it should be added as an
explicit field — flag this as an open item, not assumed already present in
`SensorFrame`.

## 4. Haptic pattern interface (forearm node only)

```cpp
enum HapticPattern {
  HAPTIC_SINGLE_PULSE,   // = 0
  HAPTIC_DOUBLE_PULSE,   // = 1
  HAPTIC_FAULT_PATTERN   // = 2
};

void triggerHapticPattern(HapticPattern pattern);
```

- Bench-verified waveforms (full duty, PWM on `GPIO25`):
  - `HAPTIC_SINGLE_PULSE`: one 150ms pulse
  - `HAPTIC_DOUBLE_PULSE`: 150ms on, 250ms off, 150ms on
  - `HAPTIC_FAULT_PATTERN`: three 150ms pulses, 100ms gaps
- `triggerHapticPattern()` is non-blocking (advanced from `loop()` via
  `updateHapticPattern()`), so it is safe to call from any future HAPTIC_CMD handler
  without adding a deliberate delay. Scheduling and communications work can still
  affect acquisition cadence and extend haptic step durations.
- Currently invoked only via a bench-test Serial hook (`1`/`2`/`3` characters). Wiring a
  received HAPTIC_CMD to `triggerHapticPattern()` is Comms' integration work; the enum
  values above are the stable contract to build the packet field against.
- Paddle node has no haptic hardware — this interface does not apply to it.

## 5. Axis convention (provisional, not final)

`AxisMapping.h` defines a per-node axis permutation + sign applied to raw counts and
physical units before they reach `SensorFrame`. The active mapping is
`AXIS_MAPPING_IDENTITY` for both channels currently — physical mounting orientation is
not yet finalized (pending Phase H pod mounting). Comms consuming absolute
direction/orientation semantics (not just raw values) should treat axis convention as
subject to change until Phase H closes.

## 6. Reference only: temporary WiFi telemetry wire format (v3)

`WiFiTelemetry.cpp`/`wifi_receiver.py` implement a throwaway UDP CSV format for
electronics-only bench validation. It is **not** the final BLE/MQTT protocol, but the
sample packets retain the raw/physical/filtered fields. Version 3 adds explicit
diagnostic metadata. Its CSV field order is:

```
3,<node_id>,<boot_id>,<burst_id>,<burst_index>,<seq>,<timestamp_us>,<interval_us>,
<ax>,<ay>,<az>,<gx>,<gy>,<gz>,
<ax_g>,<ay_g>,<az_g>,<gx_dps>,<gy_dps>,<gz_dps>,
<ax_filtered_g>,<ay_filtered_g>,<az_filtered_g>,
<gx_filtered_dps>,<gy_filtered_dps>,<gz_filtered_dps>,<status_flags>
```

`boot_id` identifies this boot; `burst_id` starts at 1 and increments at each
movement start. `burst_index` is a zero-based send-attempt index within that burst.
Acquisition sequence numbers continue through idle. These diagnostic identities
are transport metadata, not additions to the final BLE packet contract.

JSON packets on the same UDP port have `v=3`, `type`, `node`, and `boot` fields:

- `config`: actual WHO_AM_I/configuration readback, verification flag, selected
  range/scales, calibration offsets, filter alpha, movement thresholds and state.
  Sent before/after calibration and every five seconds. Use STREAMING offsets.
- `timing`: once-per-second cumulative acquisition count, interval sum/min/max,
  histogram, skipped deadlines, timing maxima, buffer drops, transmission counters,
  active/total burst IDs and gate-idle corrected sensor sums. Includes idle reads.
- `burst`: first/last acquisition sequence/timestamp, attempted/accepted/failed
  send counts, and a `closed` flag. Progress is sent during movement; final
  summaries are repeated from an eight-burst history, one per heartbeat.

`CaptureDiagnostics` owns this validation protocol. The receiver implementation is
`diagnostics/wifi_receiver.py`; the root `wifi_receiver.py` is its launcher. Every
capture saves samples and diagnostics for later plotting. See `P1_P2_TEST_GUIDE.md`
for coverage limitations and interpretation of delivery/timing statistics.
