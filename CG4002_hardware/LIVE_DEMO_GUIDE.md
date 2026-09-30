# PickleViz live hardware demo

A local browser dashboard for the P1/P2 firmware. Python 3.10+ and a current
browser are sufficient; no pip packages or Internet service are needed. Basic
display works with the original v3 firmware. **Buffered delivery and retries
require reflashing the v4 firmware**: follow [the reliability test guide](TRANSPORT_RELIABILITY_TEST_GUIDE.md)
before using this version in the presentation. Update the receiver at the same time.
The original console receiver remains available.

## Start the live demonstration

1. Connect the laptop and ESP32 to the same hotspot. The firmware destination
   must still match the laptop's current hotspot IPv4 address (last configured:
   `10.20.167.93`). If DHCP changes that address, correct it before the demo.
2. **Stop the old receiver first.** Only one process can receive UDP port 4210.
3. From the project root (`CG4002_final_project`), run:

   ```powershell
   python CG4002_hardware/demo_receiver.py --power-source lipo-usb-disconnected
   ```

   If the terminal is already in `CG4002_hardware`, run instead:

   ```powershell
   python demo_receiver.py --power-source lipo-usb-disconnected
   ```

4. A browser opens at `http://127.0.0.1:8765`. If it does not, open that address
   yourself. The Python terminal must stay running. Use **Full screen** or F11
   for projection. The page is local-only; nothing is uploaded.
5. With USB disconnected and LiPo attached, reset/power-cycle the node. Keep it
   flat, +Z upward, and motionless through calibration. Wi-Fi startup can take
   up to about 30 seconds; calibration takes roughly four more seconds.
6. Wait for **Settled**, and check **Evidence & technical details** for verified
   configuration, startup observed, and the acquisition rate.
7. Finish the last movement, hold still for at least ten seconds, then press
   **Ctrl+C in Python**. This saves the same five evidence files as the original
   receiver. Closing the browser alone does not stop the receiver.

Default captures go to a new `captures/p1_p2_<timestamp>/` folder relative to the
terminal's working directory. The terminal and page show the exact path. The
browser then shows a receiver-offline warning when Python exits; that is expected.
The power-source argument records your statement, not an electronic battery test.

## Suggested 60–90 second demonstration

- **Still on the table:** “The node is sampling at about 200 Hz. It sends
  diagnostics while idle, but gates off the full motion stream.”
- **Shake or rotate:** “The device has detected movement. The green signal is
  the magnitude of the filtered angular velocity, and a movement burst is open.”
- **Stop and hold it in the air:** “It settles again even without touching a
  table. This detects motion, not whether the sensor is on a surface.”
- **Lift and lower, then pause:** “A sufficiently brisk movement can open another
  burst; the device closes it once both signals stay below their stop thresholds.”
- **Finish still:** “For finalized bursts, we compare unique samples offered,
  accepted and received. Temporary send errors can be retried; final drops
  remain visible. Duplicates do not inflate delivery.”

Do a rehearsal with the actual mounting and hotspot before presenting. Very
gentle lifting can remain below the thresholds; a long continuous shake may be
one burst, not one burst per shake. Hand tremor can keep the gate active. Those
are threshold behaviors, not proof of a failed network connection.

## What the display means

- **Motion detected:** a new movement sample, active-burst report, or heartbeat
  identifies an active device gate. This is not an AI gesture label.
- **Settled:** a device end-of-burst report or current idle heartbeat says the
  gate is idle. It does not prove absolute stillness or measure position/height.
- **Signal interrupted:** no recent valid packets from the selected node. The
  display never converts silence into a fabricated “motion stopped” event.
- **Held readings:** idle full-resolution samples are not transmitted. The last
  movement values remain explicitly marked as held, rather than replaced by zero.
- **Rotation:** magnitude of bias-corrected, filtered gyro values, in degrees/s.
  **Acceleration deviation:** absolute difference between filtered acceleration
  magnitude and 1 g; this is not gravity-compensated linear acceleration.
- **Acquisition rate:** cumulative device register-read cadence, including idle.
  It is not screen refresh rate, UDP arrival rate, or end-to-end latency.
- **Delivery:** unique samples offered → locally accepted → unique received for
  finalized, consistent bursts starting within this capture. The denominator
  includes final local drops, but not repeat socket calls. Historical and partial
  bursts are excluded explicitly. Pending, unseen or inconsistent bursts are
  separate; late packets can revise counts. Start before reset for full coverage.
- **Buffered transmission:** pending samples are still awaiting a send outcome.
  Recovered samples succeeded after a temporary error. A retry is not itself a
  lost sample; overflow/expiry/permanent failures are final drops. The technical
  details retain boot-wide socket errors as well as current-capture statistics.
- The chart retains a peak per 50 ms display bin and shows 20 seconds of receiver
  elapsed time. It does not join different bursts or draw zero-valued idle data.
  Full-resolution evidence is unaffected by display downsampling.
- The page displays one node (default ID 1) and its current boot. Reboots clear
  its signal history; the capture still preserves every received node and boot.

The terminal also prints short human-readable events, so the demo remains usable
without the browser. Detailed config, samples and counters remain in `capture.log`.

## Replay your existing capture (optional backup / rehearsal)

From the project root:

```powershell
python CG4002_hardware/demo_receiver.py --replay captures/p1_p2_20260930_184629_738839
```

This reads the existing CSV/diagnostics, opens **RECORDED REPLAY**, and does not
bind UDP, send data to the node, create evidence, or change the source files.
Never present it as a live test. It skips the initial pre-packet wait but preserves
the intervals between received records. Add `--speed 2` to rehearse at 2x speed;
replay chart/event time stays on the recorded time scale. After completion the
page stays available until Ctrl+C.

## Options and troubleshooting

- `--no-browser`: print the URL without opening a tab automatically.
- `--http-port 8766`: choose another local dashboard port if 8765 is occupied.
- `--node-id 2`: display node 2; does not relabel firmware or alter the capture.
- Live mode accepts existing receiver options, such as `--sender-ip`, `--bind`,
  `--port`, `--duration`, `--output` (new folder only) and `--notes`.
- A port-in-use error usually means the old receiver/dashboard is still running.
- Waiting indefinitely: check board power, destination IP, same hotspot, Python's
  Windows firewall permission on that network, and the selected node ID.
- A dashboard-offline warning means the browser cannot reach Python, distinct
  from the ESP32 connection warning. Check the terminal first.

Software checks from the hardware folder:

```powershell
python -B -m unittest discover -s tests -v
```

Tests include device-state ordering, duplicate/late packets, reboot isolation,
idle/stale distinctions, HTTP assets and a localhost UDP capture with evidence
files. These do not substitute for a rehearsal with physical hardware.
