# P1 / P2 hardware capture

## Aggressive-motion fault diagnosis and retest — 2026-10-14

The current firmware uses v4 queued transport. The older v3 results below are
historical, not validation of this firmware's physical timing or delivery.

The old sketch latched `imuReadFault` after **one** failed I2C read and never
attempted another read in FAULT. This explains why a transient read failure
required a restart. Magnitude/saturation and the movement gate did not cause
FAULT. The original log does not distinguish a failed read from an invalid
buffer invariant, nor identify the underlying I2C error.

Runtime now discards failed samples and retries at the next 5 ms acquisition
slot. After 20 consecutive failed reads it reports `reason=imu_read_outage`,
closes the current burst with `interrupted=true`, and retries bus/IMU startup
once per second. Streaming resumes only after configuration verification and
a successful probe read. Boot calibration is retained; filters and the gate
restart. It never calibrates automatically while moving. Failed startup or
calibration remains a separately named fault requiring a reset and a stationary
calibration. I2C uses an explicit 5 ms transaction timeout; this is not a hard
wall-clock bound on the complete loop. Recovery includes sensor startup delays.

The six-axis LPF (`alpha=0.2`), movement thresholds, 150 ms quiet window,
200 Hz target, +/-16 g and +/-2000 dps remain unchanged. A missing sample
interrupts the quiet timer. Saturation remains a data flag (`15` during motion)
and does not stop acquisition. Rates above the selected ranges clip; recovery
cannot reconstruct clipped peaks or samples missed during an outage.

### First run: capture the failure details

1. Upload the main sketch with `ENABLE_VERBOSE_SAMPLE_LOG=false`. Keep your
   current Wi-Fi settings. For an isolated Serial test, optionally set
   `ENABLE_WIFI_TELEMETRY=false`; restore it for the Wi-Fi test below.
2. Open Serial Monitor at **115200 baud**. Keep the sensor flat, +Z up and still
   throughout **both** calibrations (about 4 seconds after Wi-Fi connects).
3. After STREAMING, send **`d`**. Leave it still for 10 seconds, then perform
   five gentle and five aggressive shake/rotation bursts, holding still for
   2–3 seconds between bursts. Send **`d`** again after shaking.
4. Paste the startup log, every `[fault]`, `[imu-health]`, and recovery line.
   `failures` counts failed streaming reads; `consecutive` resets on success;
   `saturated` counts near-range-limit samples. `seq` should keep advancing.
   Error details retain the **last failed transaction**, even after recovery.
   `stage=read_data bytes=0/12 wire=0` means the combined read returned no bytes;
   it does **not** mean that the I2C transfer succeeded. The ESP32 Wire API does
   not expose the underlying read error via `requestFrom()`; retain any ESP32
   I2C driver error lines printed nearby. `read_address` and `write` report the
   available Wire status code. Identity/config mismatch stages report readback
   failures, rather than a valid sensor sample.

The combined-read behavior and timeout API were checked against the
[ESP32 core 3.3.11 Wire implementation](https://github.com/espressif/arduino-esp32/blob/3.3.11/libraries/Wire/src/Wire.cpp).

### Second run: verify movement telemetry and timing

Restore `ENABLE_WIFI_TELEMETRY=true`, verify the laptop IP, start this command
from the hardware folder, then reset the board and repeat the same movements:

```powershell
python -B diagnostics/wifi_receiver.py --power-source usb --duration 90
```

The receiver prints IMU failure/recovery/saturation counts with timing reports
and marks interrupted bursts. Return `capture.log`, `summary.json`, and
`diagnostics.jsonl`; keep `samples.csv` for axis/filter analysis. The health
fields are optional additions to v4; old captures remain readable. Acquisition
timestamps include outage gaps; failed reads are separate from skipped schedule
slots and Wi-Fi delivery failures. Sample sequences count valid acquisitions.
UDP batches contain up to five 200 Hz samples, so datagram rate is not sample
rate. Idle diagnostic heartbeats and queued tail samples may still arrive after
the movement gate closes.

For battery validation repeat with USB disconnected and
`--power-source lipo-usb-disconnected` as described below. The supplied
`wifi_battery_test` sketch only sends a text heartbeat every two seconds; it
does not acquire IMU samples or test the main sketch's filter/state machine.

Host regression commands (Microsoft C++ Build Tools required for `.cmd` tests):

```powershell
cmd /c tests\run_imu_tests.cmd
cmd /c tests\run_tx_queue_tests.cmd
python -B -m unittest discover -s tests -v
```

The IMU test executes the actual sketch/driver/filter/gate with fake Wire I/O:
full-scale positive/negative axes, partial reads, isolated errors, sustained
outage, failed recovery attempts, successful recovery, and calibration failure.
These software checks do not validate aggressive motion on the physical board.

Software verification on 2026-10-14: FireBeetle 2 ESP32-E compilation passed
(931,895 bytes flash; 82,228 bytes global RAM), both C++ test suites passed,
and all 67 Python receiver regression tests passed. No hardware was flashed
or measured during these checks.

## Original P1/P2 capture procedure

For a professor-facing browser dashboard using this same firmware and capture
format, see [LIVE_DEMO_GUIDE.md](LIVE_DEMO_GUIDE.md). It adds readable motion
events and graphs without replacing the detailed evidence files.

Implementation is ready for a new run. Hardware results remain **pending** until
the updated sketch has been flashed and its capture reviewed. Keep the existing
video-package logs and plots as historical evidence; do not replace them with
simulated data or relabel their gyro values.

Local verification completed: firmware compiled for
`esp32:esp32:dfrobot_firebeetle2_esp32e` using installed ESP32 core 3.3.11;
21 receiver tests passed, including an actual localhost UDP capture and evidence
file export. These are software checks, not physical IMU or radio measurements.

## What changed

- P1 selects **+/-2000 degrees/s** and **+/-16 g**, both at **200 Hz**. The expected
  register values are `WHO_AM_I=0x44`, `GYRO_CONFIG0=0x27`, `ACCEL_CONFIG0=0x27`,
  and the low four bits of `PWR_MGMT0=0x0F`. Startup reads these back and faults on
  a mismatch. The driver and filtered gyro conversion share `ImuConfig.h`.
- The earlier firmware selected +/-4000 degrees/s with the +/-2000 conversion.
  Choosing +/-2000 now restores the range originally intended in the handoff.
  This gives better count resolution but half the previous actual headroom.
- Movement thresholds remain **40/15 dps**, **0.30/0.15 g**, and **150 ms quiet**.
  They now operate on correctly scaled gyro values. Their physical sensitivity
  changes relative to the old capture, so observe false starts or missing slow
  movements during this test. They are still provisional, not trained thresholds.
- P2 disables per-sample and periodic Serial printing during acquisition, uses
  400 kHz I2C, and counts expired software sample slots instead of trying to
  replay all overdue reads. Haptics and the movement gate remain available.
- Completed acquisition timestamps and adjacent-read intervals accompany every
  transmitted movement sample. Cumulative device statistics cover **all reads,
  including idle**, and reach the laptop once per second over UDP.
- Every boot and movement burst has an explicit ID. A burst's zero-based index
  counts send attempts. Final summaries report attempted, locally accepted and
  locally failed sends. The laptop counts unique received indexes, duplicates,
  reordering and accepted-but-not-received frames. Pauses never define bursts.

## Flash and collect

1. Connect the laptop and FireBeetle to the same hotspot. Verify the existing
   hotspot settings and `WIFI_LAPTOP_IP` in `CG4002_hardware.ino` still match
   the laptop's **current hotspot IPv4 address**. Port is **4210/UDP**.
2. Open `CG4002_hardware.ino` in Arduino IDE with the whole sketch directory
   present, including the new `ImuConfig.h` and `CaptureDiagnostics.h/.cpp`.
   Keep `ENABLE_WIFI_TELEMETRY=true`, `WIFI_ONLY_DEMO=false`, and
   `ENABLE_VERBOSE_SAMPLE_LOG=false`. Use the FireBeetle 2 ESP32-E board target
   appropriate to the existing board, then upload normally over USB.
3. Stop any older receiver using port 4210. From the **project root**
   (`CG4002_final_project`, containing `wifi_receiver.py`), run:

   ```powershell
   python wifi_receiver.py --power-source lipo-usb-disconnected
   ```

   Python **3.10 or newer** is required; no pip packages are needed. The same
   receiver can be launched from the hardware folder with
   `python diagnostics/wifi_receiver.py --power-source lipo-usb-disconnected`.
   If Windows asks, allow Python on the hotspot's network profile.
4. With the receiver already listening, disconnect USB and **reset or power-cycle
   the LiPo-powered board**. This produces a fresh boot ID and allows the receiver
   to observe startup. Keep the IMU flat, +Z upward, and motionless through
   calibration. WiFi connection can take up to 30 seconds; calibration then takes
   about 4 seconds plus read overhead. No Serial monitor is required for this run.
5. Wait for `[config] ... state=STREAMING ... range_readback_verified=True`.
   Keep it stationary for **10 seconds** after that. `[timing]` lines should
   continue even without movement. Initial `CALIBRATING` configuration packets
   contain placeholder zero biases; use the subsequent `STREAMING` values.
6. Lift and shake/rotate the IMU, then hold still for **2-3 seconds**. Repeat
   **three to five times**, mixing gentle and stronger movements. Return it to
   the table gently. Exact action labels are operator observations, not inferred
   automatically from the data. Separate the haptic demonstration from this run.
7. Finish with **10 seconds stationary** while the board stays powered. This also
   gives repeated final burst summaries time to arrive. Press **Ctrl+C** in the
   receiver before switching off the board. An optional `--duration 90` stops
   automatically, but make sure the last movement finishes well before the limit.

The power-source argument records **your statement** that USB was disconnected.
It is not an electronic battery measurement and does not close the other P3
checks (capacity, protection, voltage/current/runtime).

## What to send back

Each run creates a new `captures/p1_p2_<date>_<time>/` folder. It contains:

- `capture.log`: readable config, calibration, live readings, timing and final
  per-burst summaries. Paste this first, including the initial config lines and
  the **FINAL CAPTURE SUMMARY**.
- `summary.json`: structured configuration, complete-run timing histogram and
  per-burst delivery counts. Send this for the numerical review.
- `samples.csv`: **every received movement sample**, including duplicates,
  device timestamps, intervals, raw values, unfiltered physical values and
  filtered values. Keep/send this for corrected plots. Idle is intentionally not
  streamed as full sensor packets.
- `diagnostics.jsonl`: every received control/statistics packet, with laptop
  arrival time. This preserves the evolution of all-acquisition timing and idle
  means, even though the console only prints timing every five seconds.
- `metadata.json`: capture time, operator-reported power source and optional
  `--notes "..."` text.

The root `wifi_receiver.py` is now a small launcher. The maintained receiver and
its parser live in `CG4002_hardware/diagnostics/wifi_receiver.py`, beside the
firmware they match. Protocol v2 firmware is rejected with a flash instruction;
old `output.txt` remains readable by the original video-package analyzer.

Receiver regression checks can be repeated from the hardware folder with
`python -B -m unittest discover -s tests -v`.

## How to interpret the results

**P1:** `range_readback_verified=True` means the reported register values and
conversion constants agree. Check fresh gyro bias values and quiet-window
corrected gyro means, then inspect the movement response. This does not calibrate
angular-rate accuracy against a reference rotation instrument. The corrected
gyro mean uses bias-corrected, **unfiltered** samples while the gate is idle;
idle is not itself proof of physical stillness.

**P2 timing:** achieved Hz is `(N - 1) / (last_read_time - first_read_time)`,
computed with a cumulative 64-bit interval sum, so it works across the 32-bit
`micros()` wrap. The first sample's interval is zero and is excluded. The
histogram bins in microseconds are `<4000`, `4000-4499`, `4500-5499`,
`5500-5999`, `6000-9999`, `>=10000`. The displayed 4.5-5.5 ms fraction is a
descriptive +/-10% band, **not a course-defined pass criterion**. Assess the
achieved rate, full distribution, worst interval and skipped slots together.

These timestamps mark completed register reads. The driver still does not use
data-ready/FIFO synchronization, so regular read timing alone does not prove that
every individual IMU ODR update was read exactly once. `max_read_us` covers the
read/conversion/axis-mapping call; processing and data-send maxima cover their
own scopes. Diagnostic-send work affects subsequent measured intervals. These
maxima cannot simply be added into an end-to-end latency measurement.

**P2 delivery:** the device's accepted count means its UDP send API reported
success. `accepted_not_received` compares that count with unique packets saved
by this receiver for the same finalized burst. It can include receiver downtime
or receiver-side loss, not only radio loss. Starting before reboot removes one
major source of capture ambiguity. Acquisition sequence gaps between burst IDs
are intentional idle omissions and never count as missing sends.

Final burst summaries are sent at movement end and the most recent **eight**
are replayed round-robin once per second. UDP diagnostics can also be lost.
An absent final summary is reported as incomplete evidence; a heartbeat's total
burst count exposes wholly unseen bursts. Console burst totals are provisional
because late packets can arrive. The final JSON and console summary include any
late packets received before Ctrl+C. A burst still active at stop is incomplete.
If the sender summary and captured data disagree (e.g. more received than
accepted), the receiver reports inconsistent counts rather than negative loss.

Device and laptop clocks are not synchronized. No one-way latency or latency
claim is produced. P2 here covers acquisition timing and burst delivery counts;
the separate end-to-end latency method remains future work.

## Before changing the presentation

- P1: retain the verified startup configuration, calibration result, and fresh
  motion/quiet evidence. Review threshold sensitivity using this corrected scale.
- P2: retain all-read cadence measurements and completed-burst delivery counts;
  investigate any incomplete summaries, local send failures or missed slots.
- Then update screen/paragraph 04, the motion plots/threshold wording, and
  screens/paragraphs 09-10 using **this new hardware capture**. The existing
  script's old limitations have not yet been replaced with unmeasured claims.
