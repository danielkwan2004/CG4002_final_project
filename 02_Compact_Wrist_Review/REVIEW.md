# JCP5a physical review — 28 October 2026

**No repeat needed. The remaining compact-wrist-while-stepping check is supported.**
Together with the reviewed final JCP5 trial, this provides a useful air-motion
baseline for BLE migration. Keep the current parameters. BLE implementation still
requires the user's explicit green light; no migration or parameter freeze was
performed during this review.

Capture: `joint_cp5a_20261028_182134_582078`, both nodes on LiPo with USB disconnected.
The earlier full trial's disclosed overhand/sway substitution remains recorded in
its original review. This recording supplies the missing compact-stepping evidence.
Original automatic `needs_review` reports are preserved, with the exceptions below
explained from their timestamps rather than hidden or weakened.

## Motion evidence

All three numbered cues have clean input contexts: **1,060 valid samples per node
per context**, no missing sequence, invalid sample, timing discontinuity, partial
pair or unknown decision. The entire 30-second compact-stepping phase has 6,000
complete, known combined frames. All four associated captures close normally.

The ten-second stepping-only preparation has 2,001 known frames and zero motion
decisions. The two seconds immediately before each cue are also known background.
After each cue, paddle gyro RMS peaks at **241.71, 191.09 and 227.09 deg/s**, compared
with pre-cue maxima of **31.39, 30.00 and 23.83 deg/s**. Forearm peaks over those
post-cue windows are much smaller, **28.71, 32.85 and 36.61 deg/s**. Each paddle peak
is in the selected history/live output with valid, non-null paddle readings.
This supports capture of wrist-led motion while the forearm moves less, rather
than merely counting detector activity during ongoing steps.

First activity follows the printed cues by **0.945, 0.299 and 0.963 seconds**.
These include the user's reaction and execution time; they are **not measured
detector latency or independently verified motion recall**. Cue 2 has a short
forearm-led capture followed by a paddle-led capture. Four captures for three cues
are acceptable: we detect motion, not stroke classes or one segment per stroke.

## Warnings and their actual scope

**Incoming Wi-Fi gaps:** 35 missing sequence numbers per node, 70 total. Earlier
gaps occur around 23–50 seconds, before the ready reference begins at 63.812 s.
The final gaps occur around 126.83–126.91 s, after the last capture ends at
121.475 s and after the action phase ends at 125.834 s. None overlaps a cued
history/motion/ending context or the ready reference. The last five seconds of
final still contain 1,000 known-background frames, zero active and zero unknown.
Missing readings remain missing; unknown fallback is retained explicitly.

**Device scheduling warnings are separate from Wi-Fi loss:** forearm records two
skipped software slots and paddle records one. Both counts are already present in
their first timing report, before the supported hold begins at **19.845 s**, and
never increase for the rest of the recording. Forearm's only nonstandard acquired
interval is seq0→1 at **3.603 ms**. Paddle's startup seq0→1 interval is **12.141 ms**,
followed by **2.599 ms** at seq1→2. Later no-sequence-loss acquisition intervals are
normal. In particular, the paddle's timestamp-discontinuity flag refers to those
first two samples, not to wrist motion. No cause is assigned to these startup
events; they are explained exceptions before the holds/reference/actions, and
do not justify repeating this motion trial or changing the detector.

Both sensors acquire at approximately **200 Hz**. Supported-hold corrected gyro
RMS is **0.46285 deg/s forearm / 0.10903 deg/s paddle**, within the existing
1 deg/s limit. No invalid IMU reads, read failures/recoveries, saturation, device
buffer/queue drops, send failures or disconnections are recorded. There is no
recorded evidence of the earlier loose-IMU failure in this run.

## Preservation and reproducibility

- All **2,066 selected records** arrive exactly: 2,048 samples + 18 events,
  matching wire SHA-256 and a complete independent local receipt acknowledgement.
- All **1,813 required active/unknown frames** and all **51,862 received raw sensor
  inputs** are preserved. Nineteen out-of-segment fallback frames remain present.
- All four captures have normal endings, zero in-segment unknown/partial/
  discontinuity frames, no eviction or truncation. Three have 300 ms history.
  Capture 3 has 254.958 ms plus eight explicitly clipped prior-output frames;
  the overlap remains in preceding capture 2. There is no unexplained lost history.
- Native feature parity, joint/OR decisions, history and selected-output source
  replay pass. The original reports reproduce exactly; JCP4b's only inventory
  addition on replay is the subsequently generated `jcp5a_summary.json` hash.
- All **78 original capture files** and **152 existing runtime/configuration/test
  files** are unchanged. Candidate settings match the original final trial.
  Only review/status documents and an archival checkpoint are added/updated.

Reproduce the saved audit from `CG4002_two_node`:

```powershell
python -B .\reviews\jcp5a_20261028_182134\analyze.py --recompute
```

Raw hashes are in `CAPTURE_SHA256.json`; detailed measurements are in `review.json`.
Recomputed reports stay in `recomputed/`; original capture files are never rewritten.
No software implementation changed, so no firmware rebuild or new full test suite
was needed. The earlier full-suite queue-depth timing limitation remains documented
in `VALIDATION.json`; this review does not claim a fresh clean full-suite result.

## Next step

The planned mounted **air-motion** trials are complete enough to retain the current
joint detector, OR safeguard, reference method, alpha = 0.2 and history settings
as the BLE migration baseline. No extra Wi-Fi tuning or motion repeat is required.
Await the user's BLE green light, then preserve these decisions and null/gap
semantics while integrating the transport. BLE end-to-end behavior and actual
ball contact are not validated by these Wi-Fi air-motion recordings. This remains
binary motion detection/capture; classification belongs to the AI teammate.
