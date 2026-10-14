# PickleViz · In-person live demonstration guide

**Presenter:** Daniel Kwan · CG4002 · Group B17  
**Purpose:** show what the hardware does in real time, connect observations to the implementation, and explain the evidence and limitations.  
**Scope:** current node-1 forearm prototype and existing firmware. This guide does not add a new control path.

This is separate from the recorded presentation. The video's 8–10 minute limit does not establish a time limit for this component. Ask how much live-demo time is available. Rehearse a roughly **6–8 minute demonstration plus Q&A**, allowing extra time for startup and the USB transition.

## 1. Read this first: the end-to-end requirement

The rubric asks for **live sensor input → algorithmic response → actuator output**. The current implementation has two working paths:

- **Sensing path:** physical movement → IMU → ESP32 calibration/filtering/movement gate → Wi-Fi → laptop dashboard.
- **Actuator path:** a manually entered Serial command → ESP32 timed-pattern player → driver → vibration motor.

There is **no implemented automatic connection from the movement gate or an AI result to the motor**. The dashboard does not send a vibration command. With USB disconnected, the current Serial test hook is not available from the laptop.

Demonstrating both paths proves the sensing and actuator subsystems work, but **does not by itself satisfy a strict automatic sensor-to-actuator end-to-end requirement**. A dashboard state change is an output, but do not substitute it for the requested physical actuator.

**Before assessment:** confirm whether your individual hardware contribution may be assessed as these two paths within the group system. If a complete causal loop is required, the team must integrate and test the real decision/feedback-command path before the assessment. Do not assume a good explanation removes that requirement. Missing integration is not an unexpected hardware failure.

**Opening wording:**

> “I’ll first show the battery-powered sensing path reacting to real movement. Then I’ll demonstrate the motor through its existing command interface. Those two paths are implemented; the automatic classification-to-haptic connection is still an integration item.”

Do not silently press a Serial key after moving the sensor and imply that the sensor caused the vibration.

## 2. The day before: prepare and rehearse

### Hardware and safety

1. Bring the actual forearm prototype, LiPo, laptop, hotspot phone, known-good USB data cable and the connections you have already tested. Bring a suitable charging arrangement and any known-good spare you have; do not promise a spare exists.
2. Inspect the LiPo and wiring. Do not use a swollen, damaged or unusually hot cell. Check connector polarity, insulation and strain relief. Do not charge unattended or improvise a battery connection during the assessment.
3. Secure the controller, IMU, driver and battery so that a gentle rotation cannot pull a lead loose. Hold a rigid support, not the wires or battery. If the breadboard is not secure enough to move safely, fix that before presenting.
4. Use modest movements over a clear table. Do not drop, strike or violently shake the prototype to create a dramatic peak. Do not perform a full paddle swing near people with unsecured electronics.
5. Rehearse the exact transition from LiPo operation to your previously tested, board-supported USB setup. Do not improvise dual-supply wiring. Make any required connector changes with power off, according to the board's supported power arrangement.

### Freeze the tested configuration

1. Use the verified firmware and matching receiver. The expected configuration is protocol v4 with `diag_scheduler=staggered_v1` and `telemetry_headroom_us=3500`.
2. Confirm `WIFI_ONLY_DEMO=false`: the demonstration must use real IMU readings, not the separate synthetic Wi-Fi test mode. Keep verbose per-sample Serial logging disabled as in the final captures.
3. Do not retune thresholds, replace libraries, increase vibration duty or change filtering on demo day. If a necessary IP update requires reflashing, do it during setup and repeat the rehearsal checks.
4. Confirm Arduino IDE can see the board and that Serial Monitor at **115200 baud** can trigger patterns with `1`, `2` and `3`. Rehearse this before relying on it in front of the professor.
5. Test the hotspot and laptop at the actual venue if possible. A hotspot's DHCP assignment can change; “same hotspot” alone does not ensure the hard-coded destination is correct.

### Prepare the evidence tabs

Have these available locally, without relying on Internet access:

- The live dashboard, once started.
- [Presentation](Hardware_Presentation.md), especially architecture, gate logic, transport and timing.
- [Final evidence notes](README.md#evidence-used-in-this-revision).
- [Console A summary](../captures/p1_p2_20260930_213118_596228/summary.json) and [dashboard B summary](../captures/p1_p2_20260930_213429_016641/summary.json).
- [Movement plot](plots/04_verified_motion.png), [filter comparison](plots/05_verified_filter.png) and [timing comparison](plots/06_verified_timing.png).
- Arduino IDE with `CG4002_hardware.ino`; keep Wi-Fi credentials off the projected screen. Have `MoveDetector.cpp`, `ImuConfig.h`, `TxQueue.h` and `TelemetryScheduler.h` easy to locate.

The final capture folders contain the underlying CSV, diagnostics and power metadata. Keep them alongside the video package if moving the files. The package's old `evidence/output.txt` and plots 01–03 are legacy evidence, not the final timing/delivery proof.

## 3. On arrival: setup before the professor starts watching

### Step A · Check the network and laptop

1. Connect the laptop to the intended hotspot. Keep the phone nearby, powered adequately, and configured not to stop the hotspot during the session. Avoid changing networks halfway through.
2. In PowerShell, run:

   ```powershell
   ipconfig
   ```

3. Find the IPv4 address of the active hotspot Wi-Fi adapter. Do not use the gateway address, a VPN address or another adapter's address. Compare it with `WIFI_LAPTOP_IP` in the firmware. If different, correct the destination and reflash **before** the demonstration, then verify again.
4. Stop any earlier `wifi_receiver.py` or `demo_receiver.py` process with Ctrl+C. Only one live receiver should own UDP port 4210. A browser tab alone is not the receiver.
5. Ensure Python is allowed to receive UDP on the trusted network under the laptop's normal firewall policy. Do not disable the whole firewall as a shortcut.
6. Put the laptop on reliable power if available and prevent sleep for the session. Keep a terminal visible behind the dashboard so you can distinguish a browser issue from a receiver failure.

### Step B · Start a fresh battery-only capture

All commands below assume the **project root**, not the video-package folder:

```powershell
Set-Location 'C:\Users\USER\Documents\NUS\Y3S1_mods\CG4002\CG4002_final_project'
python CG4002_hardware/demo_receiver.py --power-source lipo-usb-disconnected --notes "Professor live demo: node 1, LiPo, USB disconnected"
```

Use the Python interpreter that worked in rehearsal; if it is invoked with `py` on your laptop, substitute that command consistently. The receiver uses Python 3.10+ and the standard library; no plotting packages are needed to run it.

1. Open `http://127.0.0.1:8765` if the browser does not open automatically. Keep Python running.
2. Check that this is **live mode**, not a page labelled **RECORDED REPLAY**.
3. Note the new capture directory printed in the terminal. Starting from the project root puts default captures in its `captures` folder.
4. With USB disconnected, power on/reset the LiPo-powered node **after** the receiver starts. This gives the receiver startup coverage rather than starting halfway through a burst.
5. Keep the sensor flat, +Z upward and motionless throughout startup and calibration. Allow up to roughly 30 seconds for Wi-Fi startup and about four seconds for calibration, rather than moving it as soon as an LED lights up.
6. Wait for streaming and an idle/“Settled” state. Expand **Evidence & technical details**.

### Step C · Go/no-go check

Check before beginning the explanation:

- Node 1 is the intended device; a current boot ID is visible and packet age stays recent.
- Startup was observed, and IMU register readback is verified.
- The configuration identifies `staggered_v1`; inspect the terminal/capture config if not all fields are shown on the page.
- Acquisition count increases while the device rests; mean rate is near 200 Hz once sufficient intervals have accumulated.
- No unexpected skipped deadlines, acquisition-buffer drops, final transmit drops or unresolved evidence warnings are appearing.
- A short, safe rotation produces a movement response; stopping lets the gate settle.

If you do this rehearsal in the same capture, those rehearsal bursts will be in the totals. Either explain that the capture includes setup, or stop/save it and start a fresh receiver-plus-reset sequence for assessment. Do not present accumulated setup counts as newly generated professor-demo counts.

## 4. What to show the professor, step by step

Use the pattern **action → visible observation → explanation → limitation**. Describe what actually appears, not what you expected to appear.

### Step 1 · Establish the hardware and scope — about 40 seconds

**Do:** point to the actual FireBeetle, IMU, driver, motor and battery. Show that USB is disconnected. Keep the battery and wiring supported.

**Say:**

> “The IMU measures acceleration and angular rate. The ESP32 calibrates and filters those readings, then decides when movement samples should be transmitted. The laptop displays that decision and the evidence counters. The motor has a separate driver; a GPIO controls the driver rather than supplying motor current.”

Use the scope statement in section 1. If asked about the second node, say this demonstration is node 1; do not imply the paddle node has been validated by these captures.

### Step 2 · Prove that idle is still an operating system — about 20 seconds

**Do:** leave the sensor motionless on the table. Point to the live packet age, increasing **SAMPLES ACQUIRED · DEVICE BOOT** count, and **Settled** state.

**Expected:** acquisition continues near 200 Hz; diagnostics continue; no new movement burst is needed.

**Say:**

> “Settled means the movement gate is idle, not that the sensor or Wi-Fi has switched off. Acquisition and filtering continue. I suppress full movement packets at rest, while heartbeats keep the device observable.”

If the last numerical motion reading remains visible, point out its held/stale label. Do not describe it as a new idle measurement or demand that it become zero.

### Step 3 · Cause a clear dynamic response — about 30 seconds

**Do:** smoothly rotate or gently shake the secured assembly for three to five seconds. Stop completely for several seconds. Repeat once.

**Point to:** “Motion detected,” the filtered rotation trace, new burst count and event feed; then the return to “Settled.”

**Say:**

> “The live sensor signal changes when I move it. The ESP32 opens a burst if filtered rotation reaches forty degrees per second, or acceleration magnitude differs from one g by at least point three g. The dashboard is reporting that device decision, not classifying the stroke itself.”

Explain that several shakes without a sufficiently quiet pause can be one burst. Do not expect one burst per hand movement.

### Step 4 · Show the stopping rule and its meaning — about 40 seconds

**Do:** lift the supported assembly, then hold it as steady as possible in the air. If hand tremor prevents settling, rest it on the table and explain why. Lower it gently and pause again.

**Expected:** it can settle without table contact. A sufficiently brisk lift/lower may open a burst; a very gentle one may not.

**Say:**

> “This detects motion, not height or contact with the table. To close a burst, rotation must stay below fifteen degrees per second and acceleration deviation below point one five g for a hundred and fifty milliseconds. The lower stop thresholds and quiet period prevent rapid switching.”

The 150 ms is a **device quiet-condition duration**, not a guaranteed 150 ms screen response. Filtering, scheduling, transport and display updates add delay.

### Step 5 · Show stability and completed delivery — about 45–60 seconds

**Do:** perform another modest movement interval of about ten seconds, then pause. Keep the same battery session running through your explanations. End with at least ten seconds at rest so pending work and final summaries can arrive.

**Point to:** acquisition rate and interval range; skipped deadlines/internal drops in technical details; offered → accepted → received; transmit pending/final-drop counters; capture coverage.

**Say, only if supported by the current display:**

> “The acquisition counter continued during movement and rest. For these finalized bursts, the unique offered, locally accepted and received counts agree, with no pending samples or final drops. That supports this run's delivery; it is not an unconditional guarantee about Wi-Fi.”

Do not declare success just because the mean says 200 Hz. Check interval extremes and skipped deadlines as well. Do not compare an unfinished burst's received count against a finalized total or treat partial/excluded coverage as zero loss.

If a warning appears, acknowledge it and use section 6. Do not hide warnings, reset counters to erase them, or inflate confidence from the older good runs.

### Step 6 · Save the LiPo phase, then change modes openly — allow 45–90 seconds

**Say:**

> “That completes the USB-disconnected sensing test. I’m now switching to the Serial command interface to demonstrate the actuator. This next part is not a battery-only claim and is not automatically triggered by the sensor.”

1. Let the device settle for at least ten seconds, then press **Ctrl+C in the receiver terminal**. Wait for the saved-file message and note the directory. Closing the browser alone does not save and stop the receiver.
2. Use your rehearsed USB power/data arrangement. Avoid touching exposed conductors or reworking live wiring.
3. Start a **new** receiver capture with accurate power metadata:

   ```powershell
   python CG4002_hardware/demo_receiver.py --power-source usb --notes "Professor live demo: USB Serial haptic command test; separate from LiPo phase"
   ```

4. Open Arduino Serial Monitor for the correct board port at **115200 baud**. Opening the port may reset the board. Once the receiver and Serial Monitor are ready, reset once if needed to obtain a fresh startup; then keep the IMU flat and still through calibration.
5. Confirm normal streaming before the motor test. If the new boot/startup is not fully captured, disclose that coverage limitation rather than using it for a full-run delivery claim.

Never leave the dashboard labelled “LiPo / USB disconnected” while a USB cable is attached. The power label records your declaration; it does not sense the actual power path.

### Step 7 · Demonstrate real actuator output — about 45 seconds

**Do:** keep the assembly supported. Set Serial Monitor to **No line ending** for clarity. Send each command individually, letting its pattern finish before the next:

1. Type `1` and press Send: one 150 ms pulse.
2. Wait about two seconds. Send `2`: 150 ms on, 250 ms off, 150 ms on.
3. Wait about two seconds. Send `3`: three 150 ms pulses with 100 ms gaps.

**Show:** the physical motor response and the corresponding `[haptic] pattern=...` message. Use the safe, rehearsed way of making the vibration perceptible; if appropriate, invite the professor to feel an insulated, securely mounted surface. Do not ask anyone to touch exposed wiring. A printed command acknowledgement alone does not prove the motor moved.

**Say:**

> “These commands enter a timed pattern player. It advances the PWM steps using elapsed time rather than blocking delays, so the loop can continue servicing other work. These are commanded durations; exact motor response and mounted comfort still need measurement.”

Sending another command early restarts the selected pattern, so do not send `123` as one string. `3` selects the fault-indication pattern; it does not inject an actual sensor fault.

If the dashboard stays connected while the motor runs, you may describe that **live observation**. Do not claim a completed motor-interference validation merely because no obvious problem appeared. Preserve this separate capture for inspection.

### Step 8 · Close with the evidence and boundary — about 20 seconds

**Say:**

> “You’ve seen real motion produce a device-level gate response and reach the laptop, and commands produce physical vibration. The automatic feedback-command integration remains separate. The saved evidence lets us check timing and delivery rather than relying only on what the screen looked like.”

Hold still, allow final summaries to arrive, and stop/save the receiver with Ctrl+C. Retain the day's successful and failed captures. Offer Q&A rather than continuing to shake the hardware while answering.

## 5. Likely questions and defensible answers

### “Is this genuinely end-to-end?”

“The sensing-to-dashboard path is live, and the command-to-motor path is live. They are not yet automatically connected. A complete decision-to-actuator feedback path still needs integration.” Point to the solid/dashed paths in the architecture. Do not call manual intervention autonomous control.

### “Why this IMU and ESP32?”

“The six-axis IMU provides both acceleration and angular rate for the intended motion features. The FireBeetle gives us the controller, interfaces and a battery connection for a portable prototype. Using the same sensor design for both intended nodes allows reuse of the driver and processing.” Do not claim measured accuracy, power efficiency or component superiority that you have not established.

### “Why I²C rather than the SPI in the proposal?”

“I²C simplified this prototype's wiring. I use checked 12-byte reads at 400 kHz and measure the resulting cadence. The trade-off is that this is software-scheduled acquisition, not the proposed interrupt/FIFO path.” Point to Screen 11 and the timing evidence.

### “How do you know the units are right?”

“Both final captures show verified register readback: gyro and accelerometer configuration are `0x27`. The selected ranges are ±2000 degrees per second and ±16 g, converted using 16.4 and 2048 counts per unit. That checks configuration consistency, not an independent absolute-accuracy calibration.” Point to `ImuConfig.h` and the captured config.

### “Why calibrate flat, and why subtract one from the Z average?”

“I estimate stationary gyro bias from 400 readings and accelerometer offsets from another 400. With +Z upward, the expected Z value is one g, not zero. The subtraction preserves gravity rather than incorrectly removing it as an offset.” Motion during calibration contaminates that estimate, which is why you restart calibration if disturbed.

### “Why a simple low-pass filter? What do you lose?”

“Alpha is 0.2: twenty percent new input and eighty percent previous output. It is inexpensive and smooths fast variation, but delays changes and reduces short peaks. I retain original and processed values to inspect that trade-off.” Show the filter plot; do not claim optimal filtering or preserved impact fidelity.

### “Why those thresholds? Is that AI?”

“It is a provisional movement gate, not a trained classifier. The start rule is gyro ≥40 degrees per second OR acceleration deviation ≥0.30 g. Stopping needs both lower conditions, <15 and <0.15, for 150 ms. Hysteresis and dwell time reduce chatter. The thresholds still need action-labelled validation.”

### “Why does it settle while held in the air? Why didn't a gentle lift trigger?”

“It does not measure height or table contact. The gate responds to these motion features crossing thresholds. A steady hold can be below them, and a gentle lift can also remain below them. Settled means gate idle, not guaranteed absolute stillness.”

### “Why does the plot freeze instead of going to zero?”

“Full-resolution idle samples are not transmitted. The display labels the last movement value as held; replacing it with zero would invent data. Heartbeats and the acquisition counter continue independently.”

### “Are you really sampling at 200 Hz? The screen doesn't update that fast.”

“The rate comes from device timestamps and cumulative intervals, including idle. Batching and display updates have different rates. In the two final captures, the completed-read rate averaged about 200 Hz, with all 36,279 measured intervals within 4.5–5.5 ms and no skipped deadlines or acquisition-buffer drops. This doesn't independently prove every read is a distinct hardware sensor update.”

### “Why Wi-Fi/UDP? Does a successful send mean the laptop received it?”

“Wi-Fi provides a temporary, inspectable test path before BLE integration. UDP acceptance is only a local result, so I compare unique received sample IDs against completed burst summaries. The final runs received 10,993 of 10,993 offered movement samples across 28 bursts. That's measured receipt, not a delivery guarantee.”

### “What happens if the network gets busy? Was 200 Hz too much?”

“The current design separates acquisition from a 128-sample transmit queue, batches up to five samples, and retries transient local failures later. Full batches reduce the data traffic to about forty datagrams a second without reducing the 200 Hz sample rate. Queue limits and a one-second oldest-sample expiry prevent unbounded backlog. A 3.5 ms headroom guard and staggered diagnostics protect acquisition time. These safeguards are bounded, not a cure for every outage.”

If asked specifically about the earlier failures: “Earlier logs recorded local `ENOMEM` send failures while acquisition stayed near 200 Hz. That points to local network-resource pressure, not proof that the IMU cannot sample at 200 Hz. The final queued/staggered captures show no such errors. The precise resource-exhaustion mechanism was not independently proven.” Do not simply blame the dashboard or hotspot without evidence.

### “Does a retry mean data was lost?”

“Not necessarily. A transient local error leaves the exact batch pending; a later accepted send can recover it. Final drops and accepted-but-not-received samples are separate counters. There is no end-to-end acknowledgement scheme to retransmit packets lost after local acceptance.” Neither final good capture needed retries; do not claim those runs tested live recovery.

### “What proves stability?”

“I inspect more than the average rate: interval range, skipped slots, internal drops, queue occupancy, pending samples and finalized delivery. The saved runs cover 85.21 and 96.18 seconds of acquisition. Today's capture adds evidence under today's conditions, but neither establishes indefinite reliability or battery endurance.”

### “Why not drive the motor directly? Why no delay in the pattern?”

“The GPIO is a control signal; the module supplies motor current. The firmware generates the pattern because this build uses the available three-pin driver rather than the proposed DRV2605L. Elapsed-time steps avoid intentionally blocking acquisition with delays, although slow loop work can still lengthen a pulse.”

### “How long does the battery last? Is it protected?”

“These captures document USB-disconnected LiPo operation. I do not yet have a measured endurance result or verified protection specification to present, so I won't infer either from a successful short run.” Do not quote the proposal's estimated capacity as an installed-battery fact.

### “Can it detect a stroke, reconstruct a trajectory, or validate paddle impact?”

“Not from this hardware demonstration alone. It supplies inspectable motion data and a provisional movement gate. Stroke classification, final two-node integration, mounted axes and trajectory/impact validation are separate work.”

### “What is the latency?”

“There are several delays: filtering, the 150 ms stopping condition, packet batching and scheduling, network delivery and browser refresh. The final captures recorded a maximum transmit-queue age of 25 ms, but that is not measured one-way end-to-end latency. The device and laptop clocks aren't synchronized for that claim.”

## 6. If something fails: explain, isolate, preserve evidence

### A. Use this four-sentence response

> “The observed failure is **[specific symptom]**. We can still verify **[working part]** from **[current observation]**. The evidence points to **[supported explanation or explicitly labelled hypothesis]**; **[what remains unconfirmed]**. I’ll make **[one safe check]**, then show the relevant previous capture if it doesn't recover.”

Say “I have not isolated the cause yet” when that is true. The policy rewards understanding, not a confidently invented root cause. Prior evidence supports what worked then; it does not diagnose today's failure by itself.

Unless the professor asks for more debugging, limit yourself to one or two targeted checks, roughly 60–90 seconds, then demonstrate the working remainder and use recorded evidence. Stop immediately for heat, damage, loose exposed conductors or other safety concerns.

### B. Browser blank/offline, but the terminal still receives

1. Check whether the terminal process is alive and reporting packets.
2. Reopen the printed localhost URL. If HTTP port 8765 was occupied, stop the owned old dashboard or restart with `--http-port 8766` and use the new URL.
3. If needed, stop/save the dashboard receiver and use the console receiver below. Reset after starting it for complete capture coverage.

```powershell
python wifi_receiver.py --power-source lipo-usb-disconnected --notes "Professor demo fallback: console receiver"
```

Use `--power-source usb` instead if USB is attached. Never run both receivers on UDP 4210 simultaneously.

**Explain:** “The display layer is unavailable; these live receiver events still show the device path.” Only say this if packets really are arriving.

### C. No packets, “Signal interrupted,” or a board LED with no data

1. Check Python is still running and whether the warning concerns Python itself or packets from the board. An LED alone does not prove successful IMU startup or Wi-Fi delivery.
2. Check the active Wi-Fi IPv4 destination, same hotspot and receiver ownership of UDP 4210. Check permitted firewall access without disabling general protection.
3. If necessary, save the failing capture and switch openly to USB Serial diagnostics. Look for Wi-Fi startup errors, configuration failure, calibration or a latched fault. Do not immediately assume a flat battery.
4. After a justified correction, start a new, correctly labelled capture and reset while stationary. Retain the failed run.

**Explain:** silence is not an observed movement stop. If the cause is not isolated, list the remaining candidates as hypotheses, not findings.

### D. “Motion detected” never settles, or motion does not trigger

1. Place the assembly genuinely still on the table. Check live packet age and actual gyro/acceleration values.
2. If it was disturbed during calibration, restart with a fresh capture and repeat flat, stationary calibration.
3. For no trigger, use a modest, deliberate rotation already rehearsed; very gentle movement may be correctly below threshold. Check configuration and physical connection if readings do not react.
4. Do not lower thresholds or shake dangerously just to force a favourable display.

**Explain:** threshold behaviour, bad calibration, sensor/read faults and network silence are different cases. Use the readings and state to distinguish them.

### E. “Check evidence,” send errors, or unequal delivery counts

1. Stop movement and allow ten seconds for pending samples/final summaries to settle.
2. Inspect socket errors, retry/recovered counts, pending samples, final-drop causes and accepted-but-not-received counts separately. Check whether the burst is finalized and whether startup/coverage is complete.
3. If pending becomes zero and all samples are received, describe recovered transient errors rather than claiming no errors occurred.
4. If losses remain, report the exact missing count and preserve the capture. Check the timing counters too; good acquisition and impaired delivery can coexist.

Do not call an incomplete capture lossless, or count an intentionally gated idle sequence gap as a lost active sample.

### F. Serial message appears, but the motor does not vibrate

1. Confirm the correct board port, 115200 baud and one command at a time. Check the printed pattern name.
2. A pattern message proves command handling, not physical actuation. Separate that working part from the driver/motor failure.
3. Power down before checking the GPIO25 control lead, shared ground and the rehearsed driver supply connection. Do not bypass the driver, connect the motor to GPIO, increase its supply or change battery wiring on the fly.
4. If it remains unavailable, show the pattern code and the documented earlier bench observation. Do not imply the LiPo sensor captures themselves prove motor operation; they do not.

### G. Complete hardware failure

1. Make the setup safe. Stop/save the live capture, including an empty or failed one if produced.
2. State the symptom and the known limits of your diagnosis.
3. Trace the intended signal and control paths using the architecture and source code.
4. Open the actual final summary and plots, identify the capture date/run, and explain what they establish.
5. If helpful, run the explicitly labelled replay below. Do not present it as live or as a replacement for the attempted live demonstration.

```powershell
python CG4002_hardware/demo_receiver.py --replay captures/p1_p2_20260930_213429_016641
```

Stop the live dashboard first to free its HTTP port. Do not add `--power-source` to replay mode. Replay reads saved evidence, creates no new live capture and remains labelled **RECORDED REPLAY**. Stop it with Ctrl+C.

**Evidence wording:**

> “This is the saved dashboard run from 30 September, not a live connection. It contains 19,238 acquisitions over 96.18 seconds and 5,405 offered, accepted and received movement samples across sixteen finalized bursts. It supports the earlier tested behaviour, while today's failure remains the issue I've described.”

## 7. Pocket checklist: the order to remember

1. **Scope:** disclose the automatic-feedback integration gap.
2. **Safe setup:** secured hardware, checked power, correct hotspot destination.
3. **Capture first:** one receiver, then reset; stay flat through calibration.
4. **Idle:** packet age stays fresh and acquisition count rises.
5. **Move:** input changes, gate opens, signal and burst events respond.
6. **Hold:** gate closes after the quiet conditions; holding in air is not position tracking.
7. **Stability:** inspect timing, drops, pending and finalized receipt—not just a green label.
8. **Save LiPo:** wait at rest, Ctrl+C, keep the evidence path.
9. **Declare USB mode:** new capture, correct power label, Serial at 115200, stationary startup.
10. **Actuate:** send `1`, `2`, `3` separately; show actual vibration, not only text.
11. **Close:** state what is demonstrated and what is not; save the second capture.
12. **If failure:** specific symptom, supported diagnosis, safe check, working remainder, dated evidence.

The strongest demonstration is one where the professor can see the cause, observe the response and understand exactly what the evidence does—and does not—prove.
