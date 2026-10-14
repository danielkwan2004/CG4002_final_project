# PickleViz hardware presentation: speaking script

**Presenter:** Daniel Kwan  
**On-screen document:** `Hardware_Presentation.md`  
**Target:** 9:20 including short pauses and visual changes. Submit one continuous **8–10 minute MP4**.

Read only the paragraphs under **Say**. Bracketed directions are silent production cues. Section times are rehearsal targets, not measured delivery times. Use static photos, saved plots and code throughout: **no live hardware, terminal or dashboard demonstration in the video**.

Follow each bracketed cue immediately before its next spoken paragraph. Keep that visual on screen until the next cue. Move the pointer as you speak, rather than pausing at every instruction. Table row names and code identifiers in the cues match the presentation exactly; spoken references such as “this table” and “snippet four” are part of the narration. Scroll within a screen when necessary instead of shrinking the whole section to fit.

The narration is approximately 1,130 words, excluding all bracketed cues. At 130–140 words per minute, allow roughly 8:05–8:45 for speech plus 45–60 seconds for photos, pointing and visual changes. At 135 words per minute with about 55 seconds for visual changes, the total is approximately 9:20. Rehearse the complete sequence once and check the actual duration; do not assume the target guarantees an 8–10 minute recording.

| Screen | Target interval | On-screen route |
|---|---|---|
| 01 | 0:00–0:25 | Problem and demonstrated scope |
| 02 | 0:25–1:05 | Diagram A: live bench path, planned loop, Serial-to-motor path |
| 03 | 1:05–1:55 | PHOTO A briefly; hardware/interface table top to bottom; evidence and precautions |
| 04 | 1:55–2:55 | Snippet 1 settings and period; register readback; snippet 2 read check; frame fields |
| 05 | 2:55–3:35 | Startup condition; snippet 3 Z offset; snippet 4 filter; rationale/trade-off bullets |
| 06 | 3:35–4:25 | Diagram B and snippets 5–6 |
| 07 | 4:25–5:05 | PHOTO B briefly; snippet 7 steps; pattern table; functions and recorded observation |
| 08 | 5:05–6:00 | Plot 1 panels, thresholds and gaps; Plot 2 legend and paired peaks |
| 09 | 6:00–7:05 | Snippet 8; queue/closure rules; results table down each run column; combined total |
| 10 | 7:05–8:10 | Snippet 9; headroom rule; Plot 3 line/bars/dots; acquisition table and limits |
| 11 | 8:10–8:55 | Proposal/implementation/trade-off table, each row left to right |
| 12 | 8:55–9:20 | Validated results and integration work |

---

## Paragraph 01 · Problem and scope

[Show the title, then Screen 01. Keep the “Sense”, “Decide” and “Respond” bullets visible. Point down those bullets during the second sentence, then to the final scope sentence.]

**Say**

Hi, I’m Daniel. These three steps summarise PickleViz: sense the movement, support a decision about the stroke, and provide feedback. My part is the sensing and haptic hardware. As the scope statement here shows, this presentation covers the forearm pipeline and laptop telemetry, with separately tested vibration output.

---

## Paragraph 02 · System architecture

[Show Screen 02, Diagram A. Point to “Forearm IMU + ESP32”, then follow the solid “Current Wi-Fi / UDP” arrow to “Laptop gateway”.]

**Say**

In Diagram A, follow this solid arrow from the forearm node to the laptop. That is the sensing path I’ve tested over Wi-Fi.

[Point to “Paddle IMU + ESP32”. Trace the dashed laptop → Ultra96 → laptop path, then the branches to the phone and the forearm pattern player.]

The dashed arrows show the planned system. The paddle adds a second sensing location, the Ultra96 classifies strokes, and the phone displays feedback. A command can also return to the forearm motor.

[Point to the solid “Serial command test” → forearm pattern-player arrow, then the solid/dashed legend.]

This other solid arrow is the tested Serial-to-motor path. The two bench paths work separately. The automatic AI-to-haptic connection still needs integration.

---

## Paragraph 03 · Hardware and power

[Briefly show PHOTO A, the saved overview of the actual build, for about 3 seconds. Point to the controller and IMU. Return to Screen 03 before speaking. Keep the “Hardware / interface” and “Implementation” columns visible.]

**Say**

This hardware and interface table maps the parts to their connections. The first two rows identify the FireBeetle controller and six-axis IMU.

[Point across the “I²C” row to “400 kHz; SDA GPIO21, SCL GPIO22”, then the “Sensor supply” row.]

The I-squared-C row shows the digital sensor interface on pins twenty-one and twenty-two, at four hundred kilohertz. The sensor uses three-point-three volts and a shared ground, with no external ADC.

[Point across “Haptic output” and “Driver supply”. Follow GPIO25 → driver → motor in the implementation cell.]

These haptic rows show pin twenty-five controlling the driver. The driver supplies motor current, rather than the GPIO.

[Point to “Standalone power”, then the “Evidence” and “Wearable precautions” lines below the table.]

The last row is the LiPo connection. Both final captures document USB-disconnected operation. The precautions below cover wiring and battery safety, but endurance and protection details remain unverified.

---

## Paragraph 04 · Acquisition and data contract

[Show Screen 04, snippet 1. Point to the range comments beside GYRO_CONFIG0 and ACCEL_CONFIG0, then the two LSB_PER conversion constants.]

**Say**

Snippet one puts the sensor settings and conversion factors together. These comments show ranges of plus or minus two thousand degrees per second and sixteen g. The constants underneath convert counts into physical units.

[Point to SAMPLE_PERIOD_US = 5000, then the “Both final captures” readback line and verified=true.]

The five-thousand-microsecond period sets the two-hundred-hertz target. The readback line below confirms that both final captures used the intended configuration.

[Scroll to snippet 2. Point to data[12], the readRegisters check and return false. Keep the fault-state explanation visible if possible.]

In snippet two, the driver checks a twelve-byte read before using it. Configuration or read failure puts the node into a latched fault state.

[Point to “Each frame retains…” below snippet 2, then the accuracy/mounted-axis limitation.]

The sample fields below preserve identity, timing and raw values for tracing results. The acquisition buffer also counts dropped frames rather than hiding them. Configuration checks still don't replace independent accuracy or mounted-axis validation.

---

## Paragraph 05 · Preprocessing algorithms

[Show Screen 05. Point to the “Startup condition” line before moving to snippet 3.]

**Say**

The startup line gives the calibration condition: stationary, positive Z upward. I average four hundred readings for gyro bias and another four hundred for acceleration offsets.

[Point specifically to “- 1.0” in snippet 3's offsetZ_g expression.]

In snippet three, this minus one preserves the expected one-g gravity reading. It isn't gravity removal.

[Move to snippet 4. Point first to alpha * input, then to (1.0 - alpha) * value.]

Snippet four shows the filter: twenty percent of the new input plus eighty percent of the previous output.

[Point down the “Why”, “Trade-off” and “Inspectability” bullets, following the next two sentences.]

The bullets explain the choice: little memory and computation, but delayed response and softer peaks. Keeping original and processed readings lets us inspect that trade-off.

---

## Paragraph 06 · Decision logic

[Show Screen 06, Diagram B. Start at IDLE, then trace the start-condition arrow to ACTIVE while speaking.]

**Say**

Diagram B shows the transmission decision. Follow idle to active: rotation reaching forty degrees per second, or acceleration deviation reaching point three g, starts a burst.

[Trace ACTIVE → QUIET TIMER. Point to the lower stop thresholds, then the “150 ms” arrow back to IDLE. Briefly indicate the return arrow to ACTIVE if either condition breaks.]

To return to idle, rotation must stay below fifteen degrees per second and acceleration deviation below point one five g, together for a hundred and fifty milliseconds. The quiet timer resets if either condition breaks.

[Scroll to snippet 5. Point to || in aboveStartThreshold, then && in belowStopThresholdNow. Say “or” and “and”, not the symbol names.]

Snippet five makes that distinction explicit: OR to start, AND for the quiet condition. This helps prevent rapid switching.

[Point to snippet 6's wasMoveActive || isMoveActiveNow, then the idle-acquisition sentence and provisional-threshold note beneath it.]

Snippet six keeps both burst boundary frames. Sampling continues during idle periods, even though full movement transmission stops. These remain provisional movement thresholds, not stroke labels.

---

## Paragraph 07 · Haptic control

[Briefly show PHOTO B, the saved motor/driver close-up, for about 3 seconds. Return to Screen 07, snippet 7, before speaking. Point down the three array entries in order. No live motor actuation.]

**Say**

Read snippet seven from top to bottom: on for a hundred and fifty milliseconds, off for two hundred and fifty, then on again. That defines the double pulse.

[Point to the “Double” row in the “Pattern / Commanded timing” table, then indicate “Single” and “Fault indication”.]

The table places it alongside the single and triple-pulse patterns.

[Point to triggerHapticPattern() and updateHapticPattern() in the explanation below the table.]

These functions start the pattern and advance its steps using elapsed time, without a blocking delay.

[Point to “Recorded bench observation”, then the final limitations sentence.]

The recorded observation here is that all three patterns were distinguishable at full duty. Mounted comfort, precise timing and motor interference still need testing.

---

## Paragraph 08 · Test procedure and plots

[Show Screen 08's “Test activities” line, then enlarge Plot 1. Keep both panels and the horizontal-axis label visible.]

**Say**

These tests included stationary holds, lifting and shaking. Plot one shows the final dashboard capture against device time.

[Point to Plot 1's upper gyro-magnitude panel, then its lower acceleration-deviation panel. Indicate the orange dashed start-threshold lines in both.]

Rotation is on top, with acceleration deviation underneath. That lower value measures how far the filtered acceleration magnitude is from one g. The dashed orange lines mark the start thresholds we just discussed.

[Point to a shaded burst span, then a blank gap between spans. Do not assign a specific physical action to an unlabelled peak.]

Shading marks transmitted bursts. The blank gaps contain no transmitted idle waveform. Individual physical actions weren't timestamp-labelled.

[Enlarge Plot 2. Point to its “Burst 8: first 2 seconds” subtitle and legend: grey calibrated input, blue filtered output. Indicate upper Z-acceleration and lower Z-angular-rate panels.]

Plot two zooms into the first two seconds of burst eight. Grey is calibrated input and blue is filtered output, for Z acceleration and angular rate.

[In Plot 2's lower panel, trace one positive grey peak and its lower, slightly later blue peak. Do not quote a numerical delay.]

Compare these peaks: the blue curve is smaller and slightly later. That's the smoothing trade-off, rather than proof of accurate motion reconstruction.

---

## Paragraph 09 · Device-to-laptop consistency

[Show Screen 09, snippet 8. Point to BATCH_SIZE = 5, then the “200 samples/s ≈ 40 data datagrams/s” explanation below.]

**Say**

Snippet eight groups up to five samples per datagram. As the line below shows, that reduces full-batch data traffic to about forty datagrams per second while keeping two-hundred-hertz sampling.

[Point to CAPACITY = 128, MAX_AGE_MS = 1000 and RETRY_MS = 10. Then point to the “Transient local send error” and “Unambiguous closure” bullets.]

These constants bound queue size, sample age and retry spacing. A temporary local error keeps the batch for a later retry. The closure rule here waits until movement ends and nothing remains pending.

[Scroll to “Final capture results”. Under “Console A”, point down “Movement samples offered”, “Accepted by local UDP send” and “Unique samples received”: all 5,588. Repeat under “Dashboard B”: all 5,405. Keep the table visible.]

Now read down each column of the results table. Offered, accepted and received counts match: five thousand five hundred and eighty-eight in the console capture, and five thousand four hundred and five in the dashboard capture.

[Point to the “Closed, finalized bursts” row: 12 and 16. Then point to the zero-valued final two rows and the bold 10,993 / 10,993 total underneath.]

Together, that's ten thousand, nine hundred and ninety-three samples across twenty-eight finalized bursts, with no missing accepted samples, socket errors or final drops. Neither run needed retries. The caveat below matters: this measures these captures, not guaranteed lossless UDP.

---

## Paragraph 10 · Timing validation

[Show Screen 10, snippet 9. Point to takeSlot(...), then return. Move to the “more than 3.5 ms remaining” explanation underneath.]

**Say**

In snippet nine, this guard defers network work unless a suitable slot is available. The rule underneath allows one operation per acquisition, with more than three and a half milliseconds remaining. Diagnostics are staggered too.

[Enlarge Plot 3. Point to the vertical orange 5 ms target, then the Console A and Dashboard B horizontal bars. Indicate each dark mean dot and the bar endpoints.]

In Plot three, the orange line is the five-millisecond target. The bars span each run's minimum and maximum interval. The dots show their means, close to the target.

[Return to Screen 10's “Acquisition evidence” table. Point across “Completed acquisitions” and “Measured acquisition span”, then “Mean acquisition rate”.]

The table gives the sample counts and durations behind those results. Both runs averaged about two hundred hertz.

[Point across “Skipped deadlines / acquisition-buffer drops”: 0 / 0 in both columns. Then point to the bold 36,279-interval statement and its timestamp limitation.]

This row shows no skipped deadlines or buffer drops. All recorded intervals fit the stated band, including idle.

[Point to the last table row, “Maximum diagnostic service time”: 1.017 ms and 1.056 ms. Then return to the timestamp limitation beneath the table.]

The last row shows diagnostic service cost at about one millisecond in both runs. The acquisition statistics measure completed device reads, not network arrival times or a hard real-time guarantee.

---

## Paragraph 11 · Design changes

[Show Screen 11. Point across the three column headings: “Proposal / requirement”, “Implemented choice and rationale”, “Trade-off”. Then trace the “SPI with interrupt/FIFO acquisition” row from left to right.]

**Say**

This table connects each choice to its trade-off. In the first row, I-squared-C simplifies wiring compared with the proposed SPI approach, but requires measured software timing.

[Trace the “DRV2605L haptic driver” row across to its implementation and trade-off cells.]

The driver row explains why firmware generates the vibration patterns: this build uses the available three-pin module.

[Trace “BLE node links”, then “Continuous acquisition”, left to right.]

The next rows show Wi-Fi as a temporary test link, and movement gating as a way to reduce traffic. BLE needs separate validation, and gating means the laptop doesn't retain every idle sample.

[Point across the final “Wearable end product” row to the mounting/second-node trade-off.]

Finally, the breadboard keeps connections accessible while mounting and second-node validation remain open.

---

## Paragraph 12 · Closing checkpoint

[Show Screen 12. Point down the four result bullets in order, then to the “Next” line. Finish on this screen without showing the script's follow-up slots.]

**Say**

These four results summarise the checkpoint: verified settings, measured acquisition near two hundred hertz, complete movement delivery in the final captures, and separately tested haptic patterns. The next-step line identifies what remains: the paddle node, mounted axes, BLE, automatic feedback and wearable testing. Thank you.

---

# Follow-up slots · Not part of the spoken recording

These are production and remaining-validation notes, not extra narration. Replace existing passages if new evidence becomes available; do not append material past the ten-minute limit.

| Slot | Evidence status / remaining work | Where the presentation changes |
|---|---|---|
| P1 | **Included:** both final captures verify gyro/accel `0x27`, power `0x0F`, ±2000 deg/s with 16.4 counts/(deg/s), ±16 g with 2048 counts/g. Plots use the verified configuration. Absolute sensor accuracy and mounted axes are separate tests. | Screen/paragraph 04; refreshed plots in 08 |
| P2 | **Included:** all-acquisition timing and finalized, burst-aware delivery for final console A and dashboard B. No observed missing samples, socket errors, pending bursts, skipped deadlines or internal drops in these runs. | Screens/paragraphs 09–10 |
| P3 | **Included within scope:** metadata documents operator-reported LiPo power with USB disconnected. User requested these captures only. No capacity, protection specification, current draw or endurance claim. | Screen/paragraph 03 and closing |
| P4 | **Still pending:** second-node validation, mounted axis mapping and a controlled positive saturation-flag test. Keep current results scoped to node 1. | Screen 04 and closing |
| P5 | **Select before recording:** PHOTO A — actual build, IMU, FireBeetle and battery connection; PHOTO B — motor and driver close-up. Earlier bench pattern observations are included. Mounted comfort, timing and interference remain pending. **No live demonstration.** | Paragraphs 03 and 07 |

## Recording cues to prepare

- [PHOTO A: select the real, saved overview image; confirm components are visible.]
- [PHOTO B: select the real, saved motor/driver close-up.]
- [PLOTS: open the three new `04_verified_*`, `05_verified_*`, `06_verified_*` images in separate tabs if the Markdown preview makes them too small.]
- [PREVIEW: check both Mermaid diagrams and code font size; keep the script off the captured screen.]
- [REHEARSAL: record one timed practice. Aim for 9:20; finish below 10:00 without racing the evidence sections.]

## Evidence boundaries to retain when editing

- Console A covers 85.21 seconds of measured acquisition; dashboard B covers 96.18 seconds. Do not call both exactly 90 seconds or combine them into a single continuous run.
- Longest uninterrupted movement bursts are about 9.16 and 9.98 seconds. Do not claim a completed 15-second continuous-movement stress test.
- Idle waveform samples were not transmitted. Plot gaps are not zero-valued motion or lost active samples.
- The acquisition rate counts completed register reads, not independently verified distinct IMU output updates. Device and laptop clocks do not establish one-way network latency.
- Neither final run exercised live error recovery. Retry design is implemented; the zero-error capture results are separate evidence.
- No live dashboard, terminal, shaking or motor actuation belongs in this video. Use the saved evidence; the professor's separate live demonstration is a different activity.

Source folders, exact metrics, reproduction instructions and legacy-file notes are in `README.md`.
