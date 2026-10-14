# PickleViz hardware presentation: speaking script

**Presenter:** Daniel Kwan  
**On-screen document:** `Hardware_Presentation.md`  
**Target:** 9:20 including short pauses and visual changes. Submit one continuous **8–10 minute MP4**.

Read only the paragraphs under **Say**. Bracketed directions are silent production cues. Section times are rehearsal targets, not measured delivery times. Use static photos, saved plots and code throughout: **no live hardware, terminal or dashboard demonstration in the video**.

The narration is approximately 1,170 words. At 130–140 words per minute, allow roughly 8:20–9:00 for speech plus 30–45 seconds for pointing and visual changes. Rehearse the complete sequence once and check the actual duration; do not assume the target guarantees an 8–10 minute recording.

| Screen | Target interval | Visual |
|---|---|---|
| 01 | 0:00–0:25 | Problem and demonstrated scope |
| 02 | 0:25–1:10 | Diagram A: implemented and intended paths |
| 03 | 1:10–2:00 | Physical-photo tab and interface table |
| 04 | 2:00–2:45 | Register readback and snippets 1–2 |
| 05 | 2:45–3:35 | Calibration and filter, snippets 3–4 |
| 06 | 3:35–4:25 | Diagram B and snippets 5–6 |
| 07 | 4:25–5:05 | Snippet 7 and static motor/driver photo |
| 08 | 5:05–6:00 | Plots 1–2, enlarged one at a time |
| 09 | 6:00–7:10 | Snippet 8 and closed-burst delivery table |
| 10 | 7:10–8:05 | Snippet 9, Plot 3 and timing table |
| 11 | 8:05–8:55 | Design choices and trade-offs |
| 12 | 8:55–9:20 | Validated results and integration work |

---

## Paragraph 01 · Problem and scope

[Show Screen 01 in the Markdown preview. Begin with the title visible.]

**Say**

Hi, I’m Daniel. This is the hardware implementation for PickleViz. The idea is to capture pickleball motion and turn it into useful feedback about a player’s strokes. My part is the sensing and haptic hardware. I’ll explain how the forearm prototype works, the decisions behind it, and what our recorded tests actually show.

---

## Paragraph 02 · System architecture

[Show Screen 02, Diagram A. Trace the solid forearm-to-laptop path first, then the dashed classification and feedback paths.]

**Say**

The full system has two sensing locations: the forearm and the paddle. Their data goes through a laptop to the Ultra96 for stroke classification. The phone provides visual feedback, and a command can return to the forearm vibration motor.

The solid arrows show the paths I’ve tested: forearm data reaches the laptop over Wi-Fi, and Serial commands control the motor. The dashed arrows are the planned integration. So, the sensing path and actuator path work separately; the automatic AI-to-haptic loop is not demonstrated yet.

---

## Paragraph 03 · Hardware and power

[Switch to PHOTO A: your saved overview of the actual build. Point to the FireBeetle, IMU, driver and battery connection. This is a static photo, not a live camera view.]

**Say**

Here’s the physical build. The FireBeetle reads six motion channels from the IMU: three for acceleration and three for angular velocity.

The sensor uses I-squared-C on pins twenty-one and twenty-two. Its readings are digital, so no external ADC is needed. Pin twenty-five controls the motor driver, so the GPIO isn’t supplying motor current directly. Everything shares a ground.

[Return to Screen 03. Point to the power and precaution lines.]

Both final captures were documented as LiPo-powered with USB disconnected. That demonstrates standalone operation during these tests, not battery endurance. For the wearable, connector polarity, the charging arrangement, insulation and secure mounting all matter. I’m not claiming unmeasured capacity or protection details.

---

## Paragraph 04 · Acquisition and data contract

[Show Screen 04. Point to snippet 1 and the readback values, then snippet 2. Do not read hex values or every code line aloud.]

**Say**

Before interpreting the motion, I need to know what the numbers mean. The configuration selects a gyro range of plus or minus two thousand degrees per second and an acceleration range of plus or minus sixteen g, with matching conversion factors.

The driver reads the registers back and checks them before streaming. It also checks each twelve-byte sensor read. A failure stops normal streaming and latches a fault.

Each sample keeps its sequence, acquisition timestamp and raw values. That lets me trace a laptop reading back to the device, rather than relying only on its arrival time. Readback confirms the configuration, though it doesn’t replace an independent accuracy test or a mounted-axis check.

---

## Paragraph 05 · Preprocessing algorithms

[Show Screen 05, snippet 3. Point to the subtraction of 1.0 in the Z offset.]

**Say**

At startup, I keep the sensor still with positive Z pointing upward. I average four hundred readings for the gyro bias, then another four hundred for accelerometer offsets. Notice the minus one here: it preserves the expected one-g gravity reading. This doesn’t remove gravity from the signal.

[Point to snippet 4 and the trade-off line.]

Next, each channel uses a simple low-pass filter: twenty percent of the new input and eighty percent of the previous output. It’s cheap to compute, but it also delays the response and softens peaks. Keeping the original readings lets us inspect that trade-off.

---

## Paragraph 06 · Decision logic

[Show Screen 06, Diagram B. Trace idle → active → quiet timer → idle. Then point to snippet 6.]

**Say**

The movement gate answers a simpler question than stroke classification: should I send a movement packet?

A burst starts if the filtered gyro magnitude reaches forty degrees per second, or acceleration moves point three g away from the gravity baseline. It ends only when both signals stay below their lower stop thresholds for a hundred and fifty milliseconds.

Those separate thresholds and the quiet timer prevent rapid switching around a boundary. The code also keeps the first and last frames of each burst. Sampling and filtering continue while transmission is idle, so a gap between bursts doesn’t mean the sensor stopped working. These thresholds are provisional; they haven’t been validated as boundaries between different pickleball strokes.

---

## Paragraph 07 · Haptic control

[Show Screen 07, snippet 7. Briefly show PHOTO B: a saved close-up of the motor and its three-pin driver. Do not type Serial commands or operate the motor during recording.]

**Say**

On the output side, vibration patterns are just timed steps. This double pulse has two on-periods separated by a pause.

The firmware checks elapsed time during the normal loop instead of sitting in a delay. That leaves the loop available for sensing and communications.

Earlier bench testing recorded distinguishable single, double and triple patterns at full duty. The future feedback-command handler can call the same trigger function. That’s separate from proving comfort on the arm, precise pulse timing, or interference while the motor and sensor run together.

---

## Paragraph 08 · Test procedure and plots

[Show Screen 08, then enlarge Plot 1. Point to the shaded burst spans and the blank gaps. Do not label an individual peak as a specific physical action.]

**Say**

Testing covered holding the sensor still, lifting it, shaking it and returning it to rest. These plots use the final dashboard capture.

The shaded spans show transmitted movement bursts. Between them, the gate is idle, so we don’t have the full waveform at the laptop. The physical actions weren’t individually timestamped, so I won’t assign a particular peak to a particular action.

[Enlarge Plot 2. Trace a calibrated-input peak and the smoother filtered curve.]

Here’s a two-second section of a longer burst. I used the start of the longest burst so the selection is easy to reproduce. The filtered trace is smoother, but some peaks are smaller and the response lags. That’s the filter’s behaviour, not proof of perfect motion reconstruction.

---

## Paragraph 09 · Device-to-laptop consistency

[Show Screen 09, snippet 8. Point to batch size, then move to the delivery table. Keep the table visible during the result.]

**Say**

To reduce network overhead, I group up to five samples in one datagram. That keeps two-hundred-hertz sampling while bringing full-batch data traffic down to about forty datagrams a second.

If a local send fails temporarily, the exact batch stays queued for a later retry. The queue has size and age limits, with explicit drop counters. A burst is only finalized after movement ends and nothing remains pending. Heartbeats also continue at rest, so the receiver can distinguish an idle gate from a silent device.

The receiver compares unique samples within each burst. Across the console and dashboard runs, all ten thousand, nine hundred and ninety-three offered samples were accepted and received, across twenty-eight closed bursts. There were no local socket errors or final sample drops, and neither run needed retries. That’s a measured result for these captures, not a guarantee that UDP can never lose data.

---

## Paragraph 10 · Timing validation

[Show Screen 10, snippet 9. Point to the 3.5 ms headroom rule, then enlarge Plot 3.]

**Say**

Sending packets must also leave time for the next sensor read. The scheduler allows at most one network operation per completed acquisition, and only when more than three and a half milliseconds remain. Diagnostic messages are spread across separate slots as well.

Both final runs averaged about two hundred hertz. Across more than thirty-six thousand acquisition intervals, every recorded interval was between four point five and five point five milliseconds, with no skipped deadlines or acquisition-buffer drops.

Importantly, those counters include idle periods. They measure completed sensor reads on the device, not Wi-Fi arrival timing. If a deadline is missed, the firmware counts skipped slots instead of inventing catch-up samples for the past. This is evidence for the observed cadence, not a hard real-time guarantee.

---

## Paragraph 11 · Design changes

[Show Screen 11. Move down the table as each implementation choice is mentioned.]

**Say**

A few choices differ from the proposal. I used I-squared-C instead of SPI to simplify prototype wiring, and measured the resulting software timing. The available three-pin motor driver also means the firmware generates the pulse patterns.

Wi-Fi gives us an inspectable laptop test path before BLE integration, but BLE will need its own validation. Movement gating and batching reduce packet traffic without stopping acquisition; the trade-off is that the laptop doesn’t retain every idle sample.

Finally, the breadboard keeps connections accessible. That helps validate the electronics, while the final mounting and second node remain integration work.

---

## Paragraph 12 · Closing checkpoint

[Show Screen 12. Finish here; do not show the follow-up slots in the recording.]

**Say**

So, this checkpoint gives us verified sensor settings, measured two-hundred-hertz acquisition, complete movement delivery in both final LiPo captures, and separately tested haptic patterns. Next come the second node, mounted axes, BLE and the automatic feedback loop. We now have a measured forearm pipeline to build on. Thank you.

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
