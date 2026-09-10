# Plan: FireBeetle Sensor Node Hardware Build (Sensors + Haptics only)

Scope: Section 3 (Hardware Sensors) of `CG4002_Design_Report.md` only. Excludes BLE/MQTT
(Section 4, Comms teammate), FPGA/AI (Section 5), AR visualizer (Section 6).

Starting point: existing skeleton in `CG4002_hardware/` (fake IMU, gyro-only calibration +
low-pass filter, circular buffer). All physical parts have arrived.

## Decisions

- **IMU bus: I2C** (not SPI as in the design report) — simpler wiring with the dupont/perfboard
   parts on hand. This deviates from report Section 3.2.3; flag to the team/report later, not
   part of this plan. The DRV2605L haptic path is separate: use an ESP32 PWM/analog control
   signal to its input, with no runtime I2C communication between the FireBeetle and haptic
   driver.
- **Hand-off boundary**: firmware exposes an internal callback + finalized data struct
  (extended `SensorFrame` incl. node ID, physical units, status flags) for the Comms
  teammate to wire into BLE/GATT later. No BLE code is written as part of this plan.
- **Build order**: bring up ONE node fully (forearm node — has IMU + haptic, more complex)
  end-to-end and bench-validate before duplicating wiring/firmware/enclosure to the
  second (paddle) node.
- Per report 3.3, the haptic actuator (DRV2605L + ERM) is forearm-node only; the paddle node
  is IMU-only.
- Firmware logic (buffering, device state machine, packet format, filtering behaviour) is
  hardened against simulated/fake data first, before any real IMU/haptic hardware is wired
  in — isolates firmware-logic bugs from hardware bring-up bugs.

## Phases

### Phase A — Bring-up & Safety Prep (A1/A2/A3 can run in parallel)

1. Inventory/bench check: confirm IMU breakout pinout (I2C vs SPI pads), DRV2605L breakout
   PWM/analog input and motor-output pinout, FireBeetle 2 ESP32 battery JST polarity, and
   continuity-check the LiPo before first connect.
2. Bare FireBeetle sanity check: flash the existing `CG4002_hardware.ino` as-is (fake IMU) on
   both boards, confirm Serial output on both — confirms toolchain/board package/USB-C cables
   work.
3. Read the ICM-42686-P datasheet for the I2C address and register-map essentials (WHO_AM_I,
   power/bank registers, FIFO/data-ready bit, FS range registers), and read the DRV2605L
   datasheet for its PWM/analog input mode and motor-output requirements. Check whether an
   existing Arduino/community library exists for the ICM-42686-P vs needing a custom register
   driver. **Done** — see the "Reference: Verified Register Facts" section at the end of this
   document; confirmed no usable community library exists, so Phase C will build a custom
   `ICM42686P.h/.cpp` driver.

### Phase B — Firmware Hardening on Simulated Data — *depends on A, no real IMU/haptic hardware needed*

Everything below runs on the existing fake-IMU skeleton on both boards, so it can start
immediately without waiting on wiring/soldering.

1. **Stress-test the circular buffer**: temporarily desync producer/consumer rates (slow the
   consumer or speed up the producer) to force near-full and overflow conditions; confirm no
   corruption/wraparound bugs in `addToBuffer`/`readFromBuffer`.
2. **Add overflow and occupancy monitoring**: `addToBuffer()`'s `false` return is currently
   discarded in `loop()`; add a dropped-sample counter and track the high-water mark of
   `bufferCount`.
3. **Add sample sequence numbers and timing diagnostics**: add a monotonically increasing
   sequence number to `SensorFrame` (matches the report's SENSOR_DATA "Sequence number"
   field, 4.2.3) and log per-sample producer/consumer timing via `micros()`.
4. **Implement the device state machine**: an overall node lifecycle state machine
   (`BOOT → CALIBRATING → STREAMING → FAULT`), distinct from the haptic pattern state machine
   in Phase E — matches the report's hardware-health/calibration-state tracking (3.4, HELLO
   packet in 4.2.3).
5. **Create a more realistic fake stroke generator**: replace `readFakeIMU()`'s pure random
   noise with a synthesized swing profile (accel ramp + a short high-magnitude impact spike +
   gyro arc) so filtering/saturation logic is exercised against something resembling a real
   stroke.
6. **Test whether filtering preserves a simulated impact**: run the generator's impact spike
   through the existing `LowPassFilter` and check the peak isn't excessively attenuated — the
   report explicitly warns that overly aggressive filtering would erase useful contact
   information (3.2.2); tune `FILTER_ALPHA`/cutoff if needed.
7. **Measure processing time and CPU margin**: time the consumer-side work (bias correction +
   filtering + saturation check) per sample via `micros()` and confirm headroom against the
   5 ms/200 Hz budget (3.1), before any real I2C driver overhead is added.
8. **Define the packet-ready sensor format (draft)**: sketch the extended `SensorFrame` fields
   (node ID, sequence number, physical-units placeholder, status flags) — finalized in
   Phase F once real units are known from Phase C.
9. **Add the haptic command stub**: define the haptic pattern enum and a
   `triggerHapticPattern(state)` function that just logs to Serial for now; the real DRV2605L
   PWM control signal and motor wiring come later in Phase E.
10. **Define the sensor coordinate convention**: document the intended per-node axis-mapping
    rule (paddle vs forearm) now, as a provisional convention to be confirmed once the
   3D-printed pods are in hand (Phase G). **Draft convention**: expose one right-handed
   canonical frame to downstream processing — +X points in the implement/hand forward
   swing direction, +Y points toward the player's left, and +Z points outward from the
   forearm/paddle surface. For the forearm node, map the IMU's physically measured
   forearm-longitudinal, lateral, and outward axes into canonical X/Y/Z. For the paddle
   node, map the IMU's handle-to-head, player-left/right, and face-normal axes into
   canonical X/Y/Z. Store each mapping as an axis permutation plus sign for each node;
   do not apply assumed signs yet. Confirm the actual permutations/signs after the pods
   are mounted in Phase G, including a left-handed-player adjustment if needed.

### Phase C — Real IMU Integration (forearm node) — *depends on A, B*

1. Wire the ICM-42686-P breakout to FireBeetle #1 over I2C (SDA/SCL/VDD/GND) on a
   breadboard/dupont wires first (no solder yet). **Verified** — the IMU responds at
   `0x68` with `AD0` low, and the wiring/serial bring-up is working.
2. Write a minimal I2C driver: WHO_AM_I check, configure accel/gyro FS range + 200 Hz ODR,
   read raw accel+gyro registers. **Verified** — register `0x75` returned `0x44`, the driver
   configured low-noise mode, 200 Hz ODR, ±16g accel range and ±2000 dps gyro range, and
   returned stable stationary raw samples (`az` approximately 2076 counts, close to 1g).
   Remaining work is to integrate the driver into the production sensor pipeline.
3. Replace `readFakeIMU()` in `CG4002_hardware.ino` with the real driver behind the same
   `SensorFrame (*readSensor)()` function-pointer signature already used by `Calibration.h`,
   so the calibration code needs no changes. **Verified** — real I2C reads now feed both
   calibration and the production buffer path.
4. Add raw→physical unit conversion (counts → g / °/s) using the configured FS range —
   currently missing; existing code calibrates/filters raw int16 counts directly. **Verified**
   — real frames now populate `g` and `dps` fields using the configured ±16g and ±2000dps
   scales and set `SENSOR_STATUS_PHYSICAL_UNITS_VALID`.

### Phase D — Sensor Processing Pipeline Completion — *depends on C*

1. Extend calibration: current `Calibration.cpp` only estimates gyro bias. Add a stationary
   accelerometer bias/offset check (lighter-weight than full 6-point calibration — see
   Further Considerations).
2. Extend filtering: `LowPassFilter` is currently applied to gyro channels only in the `.ino`
   loop; apply the same filter class to accelerometer channels — reuse the Phase B impact-
   preservation tuning as the starting `FILTER_ALPHA`.
3. Add axis-convention mapping constants per node (paddle vs forearm), matched to how the
   3D-printed pod mechanically keys the IMU orientation (per report 3.2.2) — refine the
   provisional convention drafted in Phase B.
4. Add saturation/validity flagging per report 3.2.2 formula (`|a_i| >= eta * A_FS`, similar
   for gyro), and roll into a status-flags bitfield.
5. Circular buffer, sequence numbers, and device state machine were already built and stress-
   tested in Phase B — this phase just wires the real driver's timing through them, no
   structural changes expected.

### Phase E — Haptic Actuator Integration (forearm node only) — *parallel with D, depends on A, B*

1. Wire the DRV2605L breakout's PWM/analog input to a dedicated FireBeetle GPIO and connect
   the ERM motor to the driver's output pads; do not place the driver on the IMU's I2C bus.
2. Confirm the breakout is configured for the DRV2605L PWM/analog input mode and document the
   required PWM frequency/duty-cycle range from the breakout/datasheet. No runtime I2C driver,
   device-ID read, library selection, or auto-calibration sequence is required for this path.
3. Replace the Phase B Serial-log stub with `triggerHapticPattern(state)` generating the real
   PWM waveform — actual invocation from a received HAPTIC_CMD is Comms' job later; for now
   bench-test by calling it directly from `loop()`/Serial command for validation.

### Phase F — Hand-off Interface Definition — *depends on D, E*

1. Finalize the extended sensor-output struct drafted in Phase B (node ID, sequence number,
   timestamp, physical-unit accel/gyro, status flags) building on `SensorFrame.h` — this is
   the contract the Comms teammate consumes; no transport code included.
2. Document expected units, ranges, and the haptic pattern enum so Comms can build the
   SENSOR_DATA / HAPTIC_CMD packet framing from Section 4.2.3 against real field names.

### Phase G — Node 1 (Forearm) Mechanical + Electrical Packaging — *depends on C, D, E*

1. Move the breadboard circuit to perfboard: solder female headers for the IMU/DRV2605L
   breakouts (keep pluggable for rework), wire the dedicated PWM GPIO to the DRV2605L input,
   solder ERM motor leads, wire the FireBeetle,
   heat-shrink all splices.
2. Mount perfboard + FireBeetle + battery inside the forearm 3D-printed enclosure pod using
   M2 screws/standoffs; connect the battery via JST/locking connector.
3. Attach the enclosure pod to the forearm elastic/compression cuff; verify a fixed,
   repeatable orientation (matches the Phase C axis-mapping assumption).

### Phase H — Node 1 Bench Validation — *depends on G*

1. Verify calibration convergence (stationary bias stable), filter behaviour, saturation
   flagging (shake test near sensor limits), 5 ms loop timing budget (measure via `micros()`)
   — reconfirm the Phase B software-only timing margin now includes real IMU I2C overhead and
   PWM control overhead.
2. Verify haptic patterns fire correctly and are physically distinguishable
   (single/double/fault).
3. Rough current-draw check (multimeter) against the report's ~85 mA estimate for the
   forearm node.

### Phase I — Node 2 (Paddle) Duplication — *depends on H*

1. Repeat Phase C–D (IMU integration + processing pipeline) on FireBeetle #2 — no haptic
   module. The Phase B firmware hardening already applies to both boards.
2. Introduce a compile-time/config node-ID differentiation (e.g. `#define NODE_ROLE`) so
   paddle vs forearm share the same Calibration/LowPassFilter/SensorFrame codebase.
3. Repeat Phase G packaging into the paddle enclosure pod, mounted near the paddle handle
   via the paddle mounting straps.
4. Repeat Phase H bench validation for the paddle node (no haptic checks needed).

### Phase J — Dual-Node Integration Check & Hand-off Package — *depends on I*

1. Wear/mount both nodes together; confirm no interference with grip/swing, cuff comfort,
   enclosure fit, sensor stability during a few sample swings.
2. Package the final hand-off: both nodes' firmware built on common modules, documented
   output struct + haptic interface (Phase F), sample Serial-logged output from both nodes
   for the Comms teammate to validate their BLE/packet layer against.
3. This is the scope boundary — BLE/GATT, MQTT, FPGA/AI, and AR visualizer integration are
   explicitly out of scope beyond this hand-off.

## Further Considerations

1. Accelerometer calibration depth: full 6-point (per-axis scale+offset via 6 orientations)
   vs. simple stationary bias-only. Recommend starting with stationary bias-only (matches the
   report's gyro-only emphasis) and only add 6-point if bench testing shows a meaningful
   offset.
2. ICM-42686-P driver: **resolved — no usable Arduino/community library exists**; confirmed by
   search. Phase C will implement a custom thin register-level driver (`ICM42686P.h/.cpp`)
   using the register facts in the Reference section below.
3. The earlier IMU/DRV2605L I2C address-conflict concern is no longer applicable: the IMU is
   the only device on the FireBeetle's I2C bus. The DRV2605L is controlled through its PWM/
   analog input path instead.
4. The Phase B fake stroke generator and timing measurements are software-only estimates —
   Phase H must reconfirm timing margin and filter tuning once real IMU I2C overhead, PWM
   control, and actual stroke dynamics are in play.

## Reference: Verified Register Facts (from ICM-42686-P and DRV2605L datasheets)

Extracted while satisfying Phase A3, for direct use in Phase C (IMU driver) and Phase E
(haptic PWM wiring/mode verification).

### ICM-42686-P (I2C mode)
- I2C address: `0x68` if `AP_AD0` pin tied low, `0x69` if tied high — confirm which your breakout
  defaults to before wiring.
- `AP_CS` (pin 12) must be tied to VDDIO (not floating) to select I2C/I3C mode instead of SPI.
- `WHO_AM_I`: register `0x75` (bank 0), expected reset value `0x44`.
- Register banks selected via `REG_BANK_SEL` (`0x76`, accessible from any bank), bits[2:0]:
  0=Bank0 (default — has ODR/FS/data registers), 1=Bank1, 2=Bank2, 4=Bank4.
- ODR select (target 200 Hz): `GYRO_ODR` bits[3:0] @ `0x4F` = `0111`; `ACCEL_ODR` bits[3:0] @
  `0x50` = `0111`.
- FS range select: `GYRO_FS_SEL` bits[7:5] @ `0x4F`; `ACCEL_FS_SEL` bits[7:5] @ `0x50`.
- Raw data registers (big-endian by default, two's-complement 16-bit): Accel X/Y/Z =
  `0x1F`–`0x24`, Gyro X/Y/Z = `0x25`–`0x2A`.
- Sensitivity scale factors: Accel LSB/g = 1024/2048/4096/8192/16384 for ±32g/16g/8g/4g/2g;
  Gyro LSB/dps = 8.2/16.4/32.8/65.5/131/262/524.3/1048.6 for ±4000/2000/1000/500/250/125/62.5/31.25 dps.
- Device boots in Sleep mode (accel + gyro both off) — `PWR_MGMT0` (`0x4E`) must set
  `GYRO_MODE`/`ACCEL_MODE` to Low-Noise (`11`) before sampling starts.
- Data-ready polling (no hardware interrupt pin in our IMU-I2C design): `INT_STATUS` (`0x2D`)
  bit 3 `DATA_RDY_INT`.

### DRV2605L (PWM/analog control path)
- The FireBeetle does not use I2C to command this driver at runtime.
- Use the DRV2605L PWM/analog input mode and connect a dedicated ESP32 PWM GPIO to the
   breakout's control input; the ERM remains connected to the driver's motor-output pads.
- Confirm the breakout's input pin naming, required PWM frequency, duty-cycle/amplitude
   relationship, and any one-time mode configuration before Phase E implementation.
- The previous DRV2605L I2C register facts are not part of the planned runtime control path.
