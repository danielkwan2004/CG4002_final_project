# PickleViz hardware presentation: speaking script

**Presenter:** Daniel Kwan  
**On-screen document:** `Hardware_Presentation.md`  
**Target:** 9:20, including tab changes and short pauses. The submission must be one continuous 8–10 minute MP4.

Read only the paragraphs under **Say**. Bracketed directions are production cues. The timestamps are rehearsal targets, not measured delivery times. Keep the preparation appendix off-screen during the main recording.

The main narration contains approximately **1,140 spoken words**. At 130–140 words per minute, allow about 8:10–8:50 for speech, plus 30–50 seconds for pointing, tab changes and the optional motor demonstration. Rehearse once and use the section targets to stay below ten minutes.

| Screen | Target interval | Visual |
|---|---|---|
| 01 | 0:00–0:25 | Problem and hardware scope |
| 02 | 0:25–1:10 | Diagram A: system architecture |
| 03 | 1:10–2:10 | Physical-photo tab and wiring table |
| 04 | 2:10–2:50 | Code snippets 1–2 |
| 05 | 2:50–3:45 | Code snippets 3–4 |
| 06 | 3:45–4:35 | Diagram B and snippets 5–6 |
| 07 | 4:35–5:15 | Snippet 7 and motor photo/demo |
| 08 | 5:15–6:15 | Plots 1–2 |
| 09 | 6:15–7:15 | Matched values and movement-gap logs |
| 10 | 7:15–8:05 | Plot 3 and diagnostic excerpt |
| 11 | 8:05–8:55 | Design-change table |
| 12 | 8:55–9:20 | Checkpoint and next steps |

---

## Paragraph 01 · Problem and scope

[Show Screen 01 in the Markdown preview. Start the recording with the title visible.]

**Say**

Hi, I’m Daniel, and this is the hardware sensor implementation for PickleViz. Our goal is to capture pickleball motion and support useful feedback about a player’s strokes. My part covers the sensing electronics, preprocessing and haptic output. Today I’ll show the forearm prototype, explain the implementation decisions, and use actual device and laptop logs to evaluate its behaviour.

---

## Paragraph 02 · System architecture

[Show Screen 02, Diagram A. Trace the solid sensor-to-laptop connection first, then the dashed downstream path.]

**Say**

The proposed system uses one sensing node on the forearm and another near the paddle handle. The laptop coordinates their data, the Ultra96 performs stroke classification, and the phone presents visual feedback. A feedback command can then return to the forearm motor.

The solid lines show the current bench paths. The forearm sends data through a hotspot using temporary WiFi telemetry. I test the motor using Serial commands. The dashed lines show the intended final integration, including BLE and the automatic feedback command. The complete sensor-to-AI-to-actuator loop is still an integration task.

---

## Paragraph 03 · Hardware and power

[Switch to your physical-photo tab. Point to the FireBeetle, IMU and breadboard connections. Then point to the haptic module and motor. Allow about 8 seconds total for pointing and switching.]

**Say**

Here is the current physical build. The FireBeetle reads an ICM-42686-P, which measures three acceleration axes and three angular-velocity axes. I chose the same sensor for both intended nodes to share the driver and processing code. Its wide measurement range also suits dynamic sporting movements.

The IMU uses I-squared-C on GPIO21 and GPIO22. The haptic module has a separate control input on GPIO25, with a shared ground. The module supplies the motor current.

[Return to Screen 03 and point to the battery row.]

The intended standalone supply is a single-cell LiPo through the FireBeetle battery connector. Polarity, cell protection and insulation are important, especially for a wearable. Battery-only runtime remains a separate validation item. The breadboard keeps the connections accessible while I complete these checks.

---

## Paragraph 04 · Acquisition and data contract

[Show Screen 04. Highlight snippet 1, then snippet 2. Do not read every code line aloud.]

**Say**

Snippet one sets a five-millisecond acquisition target and a 256-frame buffer. Each frame carries its node identity, sequence number, timestamp, sensor values and status flags.

Snippet two shows an important driver correction. Acceleration occupies the first six bytes and the gyro occupies the next six. An earlier offset error read timestamp registers as gyro data. The corrected twelve-byte burst restores all three gyro channels.

There is also a separate gyro range-and-conversion mismatch to resolve. I therefore describe the existing gyro plots as firmware-reported values, without claiming verified absolute angular-rate accuracy.

---

## Paragraph 05 · Preprocessing algorithms

[Show Screen 05, snippet 3. Point to the subtraction of 1.0 in the Z-offset expression.]

**Say**

Calibration happens before normal acquisition. The sensor stays stationary, with positive Z pointing upward. The gyro bias is the average of 400 readings. The accelerometer offsets use another 400 readings, preserving the expected one-g gravity component. This is an offset calibration, so mounting and scale accuracy still need their own checks.

[Show snippet 4.]

Each channel then uses a first-order low-pass filter. With alpha set to point two, the new output combines twenty percent of the current input with eighty percent of the previous output. This needs very little memory or computation. The trade-off is delayed response and smaller short-duration peaks. I keep the raw and processed readings available so that this effect can be inspected.

---

## Paragraph 06 · Decision logic

[Show Screen 06, Diagram B. Follow idle, active and quiet states. Then point to snippets 5 and 6.]

**Say**

The movement detector decides when to transmit. It starts a burst when either the filtered gyro magnitude or acceleration deviation crosses its start threshold. To finish, both signals must stay below their lower stop thresholds for 150 milliseconds.

These different thresholds provide hysteresis, and the quiet period reduces repeated switching. The values are provisional and will need retuning after the gyro scale correction.

Snippet six includes the boundary sample when movement starts or ends. Acquisition and filtering continue while the gate is idle. Separately, the node tracks boot, calibration, streaming and fault states. This detector is a simple transmission gate; stroke classification belongs to the downstream AI.

---

## Paragraph 07 · Haptic control

[Show Screen 07, snippet 7. Switch briefly to the close-up of the motor and driver.]

**Say**

The actuator uses a small ERM motor and the three-pin driver actually available for this build. Snippet seven defines the double pulse as two 150-millisecond pulses separated by 250 milliseconds.

The pattern player checks elapsed time on each loop, so it avoids a blocking delay. Full duty gave a clear response in bench testing. The hardware plan records distinguishable single, double and triple patterns.

[Optional within this section: show Serial keys 1, 2 and 3 and the motor response for about 5 seconds. If only photos are available, point out the connections and retain the recorded-observation wording.]

The eventual communications handler will call the same trigger function. Mounted comfort and exact timing still need checking.

---

## Paragraph 08 · Test procedure and plots

[Show Screen 08, then enlarge Plot 1.]

**Say**

For this capture, I left the sensor stable on the table, lifted it, shook it in the air, held it still, and dropped it back onto the table. The log does not timestamp each physical action, so I have plotted actual sample sequences without inventing those boundaries.

Plot one shows a recorded transient followed by settling. At the highlighted sample, Z acceleration reaches about eight point two g before filtering, while the filtered value is about one point eight g. Later readings settle close to the gravity baseline.

[Show Plot 2. Pause briefly so the input and filtered curves are readable.]

Plot two shows the smoothing more clearly during another burst. It also shows why filter tuning matters: the peaks become smaller and delayed. This demonstrates the processing behaviour, while impact preservation still needs evaluation.

---

## Paragraph 09 · Device-to-laptop consistency

[Show Screen 09, the comparison table for sequence 6560.]

**Say**

At sequence 6560, the Serial and Python logs show matching filtered values. Across all eleven overlapping sequences, the six channels agree within the Serial display’s rounding. That supports correct transfer of those processed frames.

Status fourteen combines the physical-unit, processing and movement flags. It does not independently certify measurement accuracy.

[Point to log excerpt 2, then the receiver GAP explanation.]

One apparent receiver gap has a useful explanation. The device ends a burst at 6549 and restarts at 6560, intentionally omitting ten idle samples from transmission. The receiver’s timeout heuristic reports this as a gap. An earlier warning lacks corresponding Serial coverage and remains unresolved. These extracts therefore do not establish a packet-loss percentage.

---

## Paragraph 10 · Timing validation

[Show Screen 10, Plot 3. Point to the producer-deviation chart before the processing chart.]

**Say**

The statistics report zero buffer drops, and the buffer high-water mark stays at one frame. However, these counters only cover the internal pipeline.

The largest measured processing time is 164 microseconds. The producer timing is less stable, with a maximum interval deviation of about 22 point 6 milliseconds. This run therefore does not validate sustained 200-hertz acquisition.

The printed CPU margin excludes acquisition, verbose Serial output and WiFi sending. Long Serial lines are a likely bottleneck. My next timing test will reduce that output and capture sample timestamps. The WiFi send-call duration also measures local work, rather than end-to-end network latency.

---

## Paragraph 11 · Design changes

[Show Screen 11. Move down the table as you mention each change.]

**Say**

Several implementation decisions changed from the proposal. I used I-squared-C instead of SPI because it simplified the available wiring. This makes timing validation particularly important.

I replaced the proposed DRV2605L with the three-pin driver on hand, so the firmware now supplies the pulse patterns. Temporary WiFi makes data visible before the final BLE integration, but UDP delivery still needs measurement.

I also kept the circuit on a breadboard and added movement-gated transmission. These choices support bench debugging, while leaving mounting and burst handling as follow-up work. The gyro byte-offset repair is a separate bug fix. The remaining scale mismatch is explicitly tracked for correction and revalidation.

---

## Paragraph 12 · Closing checkpoint

[Show Screen 12. Finish here. Do not continue into the preparation appendix in the main recording.]

**Say**

This checkpoint demonstrates a working forearm sensing pipeline, inspectable preprocessing, matching laptop values and bench-tested haptic patterns. The next steps are gyro scale alignment, complete timing and delivery measurements, and battery-only validation on both nodes. The hardware plan keeps those electronics checks ahead of soldering and final enclosure design. Thank you.

---

# Follow-up slots · Not part of the spoken recording

Complete these after reviewing the main draft. They correspond to Appendix A of `Hardware_Presentation.md`. No new test result is assumed.

| Slot | Information to add later | Where the final presentation changes |
|---|---|---|
| P1 | Gyro register readback, chosen range, matching conversion factors, new capture: **[PENDING]** | Screen/paragraph 04; plots and threshold discussion if data changes |
| P2 | Timestamped acquisition intervals and burst-aware sent/received counts: **[PENDING]** | Screens/paragraphs 09–10 |
| P3 | Actual battery details, capture power source, USB-disconnected result: **[PENDING]** | Screen/paragraph 03 and final checkpoint |
| P4 | Second-node ID, calibration, axis mapping, controlled saturation test: **[PENDING]** | Screens 04–06 and final checkpoint |
| P5 | Photo selection and optional motor demonstration; mounted observations: **[PENDING]** | Screen/paragraph 07 |

**Optional replacement sentence for paragraph 03, only after P3 is evidenced:**

“For the standalone test, I disconnected USB and ran from **[battery details]** for **[duration]**. The node **[observed boot, calibration and telemetry result]**.”

**Optional replacement for paragraph 04's final passage, only after P1 is evidenced:**

“I aligned the selected gyro range and conversion factor, then checked **[register readback and new validation result]**. These updated plots use the corrected configuration.”

**Optional replacement for paragraph 10's timing passage, only after P2 is evidenced:**

“With **[logging configuration]**, I measured **[sample count]** samples over **[duration]**, with **[interval statistics]**. The corresponding transport test recorded **[defined delivery result]**.”

Replace existing sentences rather than adding a new section, so the recording remains under ten minutes. Keep unresolved limitations in the narration if the evidence is still missing.
