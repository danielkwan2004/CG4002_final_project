# CG4002 BLE movement telemetry

This is an independent spin-off of the working Wi-Fi firmware as of 2026-10-14.
The original sketch and modules remain untouched. A restorable Wi-Fi snapshot is
in `../checkpoints/wifi_working_20261014/CG4002_hardware.zip`, with per-file hashes
in `SHA256.json`. The checkpoint notes the user's enclosed-pod validation.

## Flash and run

1. Open **CG4002_ble.ino in this folder**, not the original Wi-Fi sketch. Keep all
   adjacent `.h` and `.cpp` files present; this folder is a standalone Arduino
   sketch and can be copied elsewhere without the Wi-Fi project.
2. Select **FireBeetle 2 ESP32-E**, the correct COM port, and **Upload Speed 115200**.
   Use **NimBLE-Arduino 2.5.1** (already installed on the development laptop).
   ArduinoJson is not needed. Upload normally; no upload was performed by Codex.
3. Keep the IMU flat, +Z upward, and stationary through both boot calibrations
   (about four seconds after startup). Serial Monitor remains optional at 115200.
4. Turn on the laptop's Bluetooth. From the hardware project directory:

   ```powershell
   python -m pip install -r CG4002_ble/requirements.txt
   python -B CG4002_ble/ble_receiver.py --power-source usb --duration 90
   ```

   The receiver finds **CG4002-Forearm**, connects, subscribes, and reconnects after
   link loss. No hotspot, IP address, Windows pairing step, HELLO message, or
   clock-sync handshake is required for this bench telemetry version.
5. Remain still for ten seconds, perform repeated gentle/aggressive movements,
   pause between them, and finish with ten seconds stationary. For the battery
   test, start the receiver first, disconnect USB and reset the battery-powered
   node; use `--power-source lipo-usb-disconnected`.

Remove `--duration 90` to run until Ctrl+C. Use `--address <Bluetooth address>` to
select a specific device, or `--name <name>` after changing `BLE_NAME` in the sketch.
Only one laptop connection is supported at a time.

Each run saves every received sample in `CG4002_ble/captures/ble_<timestamp>/`:
`samples.csv`, `status.jsonl`, `capture.log`, `summary.json`, and `metadata.json`.
The console prints representative samples twice per second and every movement
boundary. Console line rate is not the acquisition rate.

## Preserved sensor behavior

- ICM-42686-P on SDA 21 / SCL 22, 400 kHz I2C, 5 ms timeout.
- +/-16 g and +/-2000 degrees/s, 200 Hz target; the original register driver,
  calibration, axis mapping, filter and movement detector are independent copies.
- Boot gyro/accelerometer calibration and six-axis LPF with alpha 0.2.
- Movement starts at filtered gyro magnitude >=40 dps OR acceleration magnitude
  deviation >=0.30 g. It ends after 150 ms with gyro <15 dps AND deviation <0.15 g.
- Only movement samples, including start/end boundary samples, are notified.
  Four samples normally share one notification. A partial end batch is flushed.
- Saturation is a status flag, not a fault. Failed reads are discarded; 20
  consecutive failures trigger automatic reinitialization once per second.
  Recovery retains valid boot calibration and resets filter/gate state.
- Serial `d` prints health/timing/BLE counters; `1`, `2`, `3` play the existing
  GPIO25 haptic patterns. BLE haptic commands are outside this telemetry spin-off.

The new loop processes each acquired frame immediately, so the old redundant
producer/consumer ring is omitted. The transmit queue remains bounded at 128
samples. UDP, Wi-Fi settings, Wi-Fi diagnostics, and the Wi-Fi-only demo are absent.

## BLE behavior and interpretation

NimBLE notifications follow the working example's approach, but use dedicated
UUIDs and a smaller movement-only protocol. Use **this folder's receiver**;
the reference sketch's handshake receiver and the Wi-Fi receiver are incompatible.
Unlike the example's m/s² payload, **acceleration stays in g**, including gravity;
gyro stays in degrees/s. Both are calibrated and low-pass filtered. Raw and
unfiltered channels are still computed locally but are not transmitted.

The device requests MTU 185 and connection intervals of 7.5–15 ms; the laptop
chooses actual connection parameters. Batches shrink to fit the negotiated MTU.
**MTU must be at least 59** to fit one complete sample. The receiver reports a
clear error if negotiation remains below that limit. This implementation never
silently truncates a sample to the default 20-byte notification payload.

Acquisition continues while disconnected. Movement samples generated without a
subscription or adequate MTU count as `offline` and are not replayed. A connection
or subscription change clears pending samples and advances the session ID.
Temporary notify failures retry after 10 ms; queue overflow or one-second expiry
counts as `dropped`. `accepted` means NimBLE accepted the notification, not proof
that the laptop saved it. `offered = accepted + dropped + pending` applies to the
queue; `offline` is separate. Counters are cumulative since boot.

There are no periodic idle sensor notifications. The receiver requests a status
read once per second to distinguish an idle sensor from a lost connection/fault.
Status values are refreshed once per second. Its `hz`, `min_dt`, `max_dt`, and
`skipped` describe acquisition since boot, including idle time and outage gaps.
These are completed-read timings, not proof of unique IMU data-ready updates.

Sequences advance on every valid acquisition, including idle. Consequently gaps
**between** bursts/sessions are expected. The receiver counts gaps **within** a
burst and records missing start/end boundaries as incomplete coverage. A mid-burst
connection is partial coverage. Silence never establishes movement end. A fault
interrupts movement without fabricating an end sample; inspect `status.jsonl`.
BLE capture has less delivery-accounting detail than the archived Wi-Fi v4 tool;
it does not claim end-to-end latency, complete delivery, or battery runtime.

## Wire format

Service: `b26b1000-0ec1-4b8c-9f78-f25e5c9d4002`.
Notifications: `b26b1001-0ec1-4b8c-9f78-f25e5c9d4002`.
Read-only JSON status: `b26b1002-0ec1-4b8c-9f78-f25e5c9d4002`.

One notification is an 18-byte little-endian header (`<2sBBBBIII`) followed by
1–4 samples. Header fields: magic `CG`, version 1, node ID, sample count, reserved
zero, boot ID, connection/subscription session ID, movement burst ID.
Each 38-byte sample (`<III6fBB`) contains acquisition sequence, device timestamp
in microseconds, adjacent-read interval in microseconds, filtered ax/ay/az in g,
filtered gx/gy/gz in dps, original status flags, and event byte (0=ordinary,
1=start, 2=normal end). Device timestamps wrap at 32 bits. No cross-clock latency
calculation is made. Normal movement status is 14; saturated movement status is 15.

## Software checks

From this folder, on Windows with Microsoft C++ Build Tools and Python installed:

```powershell
cmd /c tests\run_tests.cmd
```

The tests compile the actual BLE sketch's processing loop with fake hardware,
exercise the real bounded BLE queue, and decode a C++-generated binary fixture in
Python. Live Bluetooth discovery, negotiated throughput, Windows adapter behavior,
and battery operation still require the hardware test above.

Validated on 2026-10-14: the queue and sensor-pipeline C++ tests and all eight
Python receiver tests passed, including simulated disconnect/reconnect and file
capture. The FireBeetle 2 ESP32-E Arduino build passed with NimBLE-Arduino 2.5.1:
637,535 bytes of flash (48%) and 43,984 bytes of static RAM (13%). All 53 original
checkpointed files matched their saved SHA-256 hashes; archive contents were also
verified. No BLE firmware upload or live BLE hardware test was performed.

API references: [NimBLE notifications](https://h2zero.github.io/NimBLE-Arduino/class_nim_b_l_e_characteristic.html),
[Bleak client and notification API](https://bleak.readthedocs.io/en/latest/api/client.html).
