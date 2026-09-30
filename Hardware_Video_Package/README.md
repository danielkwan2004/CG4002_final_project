# PickleViz hardware video package

Use **Hardware_Presentation.md** as the audience-facing document and **Hardware_Speaking_Script.md** as off-screen narration. The 12 screens and 12 matching paragraphs target a continuous **9:20 MP4**, within the required **8–10 minutes**. Rehearse to establish the actual duration.

The video explains the implementation using saved evidence. **Do not run a live hardware, motor, terminal or dashboard demonstration in the recording.** The professor's separate live demo is a different activity.

## Files and viewing

- `Hardware_Presentation.md`: concise screen content, two editable Mermaid diagrams, nine short code excerpts and final-capture figures/results.
- `Hardware_Speaking_Script.md`: conversational narration, section targets, bracketed visual/pointing cues and P1–P5 follow-up slots.
- `plots/04_verified_motion.png`: timestamped movement signals from final dashboard capture B; gaps are not filled with invented idle readings.
- `plots/05_verified_filter.png`: first two seconds of B's longest burst, with calibrated input and filtered output.
- `plots/06_verified_timing.png`: observed min/mean/max completed-read intervals for A and B, including idle acquisition.
- `verified_metrics.json`: source hashes, exact timing, delivery and transport results used by the figures.
- `build_verified_plots.py`: reproducible final-capture checks and plotting.

Use a Markdown preview with Mermaid support. These are scrollable presentation screens, not a paginated PowerPoint file: frame the relevant code, diagram or table as directed by the script. Open the saved plots as separate image tabs when needed for legibility. Keep the whole package together to preserve relative image links.

Actual hardware photographs remain user-supplied. Select an overview of the build/battery and a motor/driver close-up before recording. No photos have been fabricated or assumed to show unseen details.

## Evidence used in this revision

Both captures are node 1, protocol v4, scheduler `staggered_v1`, with verified register readback and startup observed. Power metadata in each states `lipo-usb-disconnected`; this is an **operator report**, not electronic battery detection.

- **Console A:** [`../captures/p1_p2_20260930_213118_596228/summary.json`](../captures/p1_p2_20260930_213118_596228/summary.json), boot `b3d2e327`. 17,043 acquisitions across 85.209776 seconds; 17,042 intervals; 4.774–5.142 ms; 12 finalized bursts and 5,588 offered/accepted/uniquely received movement samples.
- **Dashboard B:** [`../captures/p1_p2_20260930_213429_016641/summary.json`](../captures/p1_p2_20260930_213429_016641/summary.json), boot `1e5df4a0`. 19,238 acquisitions across 96.184776 seconds; 19,237 intervals; 4.776–5.131 ms; 16 finalized bursts and 5,405 offered/accepted/uniquely received movement samples.
- Supporting files in each source folder: `metadata.json`, `samples.csv`, `diagnostics.jsonl` and `capture.log`. The plot builder records SHA-256 hashes for its source inputs.

Combined: **10,993 movement samples across 28 finalized bursts**, no missing accepted samples, local socket errors, retries, final drops, duplicates, reorderings or conflicting packets. All **36,279 acquisition intervals** are in the firmware's 4500–5499 microsecond bin; exact extrema also fit the stated 4.5–5.5 ms band. Neither run has skipped deadlines or acquisition-buffer drops.

The transmit queue reached 6/128 samples and a maximum recorded age of 25 ms in each run. This is queue age, **not end-to-end latency**. The 256-frame acquisition ring and 128-sample transmit queue are different buffers. Run A records one Wi-Fi disconnect during startup, before its first timing report; do not claim the entire boot had zero disconnects.

### Interpretation limits

- Acquisition timing is cumulative through each latest received timing report and includes idle. Movement CSV rows are a subset, not the denominator for the acquisition rate.
- Closed-burst delivery compares offered samples, local UDP acceptance and unique receipt. It is not an acknowledgement/retransmission protocol for remotely lost UDP packets. Live retry recovery was not exercised by these zero-error final captures.
- The two runs are separate, not one continuous three-minute test. A covers 85.21 seconds and B covers 96.18 seconds despite the operator notes calling each a final 90-second test. Longest movement bursts are approximately 9.16/9.98 seconds, not 15 seconds.
- Register readback establishes range/conversion agreement; completed-read timestamps establish software read cadence. Neither establishes absolute motion accuracy or that each read is a distinct IMU output update.
- No synchronized physical-action labels, ground-truth trajectory or one-way network latency are available. Do not relabel an unannotated peak as a hit, lift or shake.
- No capacity, cell-protection specification, current draw or endurance result is claimed. User requested only documented LiPo captures.
- Haptic observations come from the earlier hardware-plan Phase E bench testing, separately from the final LiPo captures. Mounted comfort, exact pulse timing and simultaneous motor/sensor interference remain open.

## Code and design provenance

Code excerpts are from the sibling `CG4002_hardware` directory; explanatory comments and omitted context are marked on screen.

- Screen 04: `ImuConfig.h`, `ICM42686P.cpp`, `SensorFrame.h`, startup/fault handling in `CG4002_hardware.ino`.
- Screen 05: `Calibration.cpp`, `LowPassFilter.cpp` and the sketch's processing path. The gyro plot input is reconstructed from raw counts minus measured bias; `gx_dps`/`gy_dps`/`gz_dps` themselves are not bias-corrected.
- Screen 06: `MoveDetector.cpp`, `MoveDetector.h`, boundary-frame logic in the sketch.
- Screen 07: haptic step arrays/player in the sketch; recorded observations in `HARDWARE_PLAN.md`, Phase E.
- Screens 09–10: `TxQueue.h`, `TelemetryScheduler.h`, `CaptureDiagnostics.cpp` and `diagnostics/wifi_receiver.py`.
- Screens 02/11: intended architecture and proposal comparison in `../CG4002_Design_Report.md`; current implementation in the above source files. Proposed battery estimates are not treated as installed hardware specifications.

## Rebuild the final figures

Requires Python, NumPy and Matplotlib. From this package directory:

```powershell
python build_verified_plots.py
```

The default input is the sibling `captures` directory and only the two named final runs are used. Override paths with `--captures PATH --output PATH` if the package is moved. The builder validates configuration, complete burst accounting and zero-error capture invariants before generating figures; a changed source capture causes a failed check rather than silent substitution. It writes only the three new figures and `verified_metrics.json`, never the raw captures.

`evidence/output.txt`, `analyze_logs.py`, `log_metrics.json` and plots `01`–`03` are **preserved legacy evidence**. They are no longer used in the presentation. Do not run the legacy analyzer expecting it to regenerate the final figures. The pre-refresh presentation, script and README are preserved in `archive/pre_refresh_20260930/`.

## Before recording

1. Select the two real hardware photos and check that every part you point to is visible.
2. Preview both Mermaid diagrams and every plot; choose a readable zoom. Keep script, follow-up slots and this README off the captured screen.
3. Rehearse all 12 sections continuously. Include switching time; target 9:20 and stay below ten minutes.
4. Record explanation and static evidence only. Do not operate hardware or run a receiver in the video.
5. Check the final MP4 duration and playback. A Markdown rewrite does not produce or certify the final video.

P1 and P2 are incorporated. P3 is limited to documented battery-only captures. P4 and the mounted parts of P5 remain explicit integration/validation work, not hidden completion claims.
