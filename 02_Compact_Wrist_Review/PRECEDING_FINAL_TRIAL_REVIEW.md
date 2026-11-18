# Final JCP5 physical review — 28 October 2026, 13:50

Capture: `joint_cp5_final_20261028_135030_331487`.

**Keep this recording. No full five-minute repeat is needed.** Sensor acquisition,
all 22 recorded motion contexts, history/endings and selected-output receipt are
healthy. The automatic first-close-cue warning is explained by its short cue
window. The user's disclosed substitution leaves **compact wrist motion while
side-stepping unconfirmed**. Run the short JCP5a for that action only before
freezing the current air-motion detector. BLE migration has not begun and still
requires the user's explicit green light.

## Operator note and scope

The user reports mixed cue 3, at **309.728827 s**, was performed as an **overhand
movement while swaying** instead of the requested small wrist rotation while
side-stepping. All other cues were followed to the best of their ability.

`USER_NOTE.json` records this statement separately. The original protocol,
requested-action labels, samples and automatic reports are unchanged. This cue
is useful motion/data evidence for the reported action; it is **not** evidence
that compact wrist motion during stepping was tested. This is not an IMU-derived
stroke classification. All path names remain physical instructions only.

## Sensor and data quality

Forearm receives **64,986 samples**, paddle **66,452**, at approximately
**200.000 Hz** each. Both start at sequence zero with one boot, correct stored
sensor calibration/profiles, continuous input mode and alpha = 0.2. Corrected
stationary raw gyro RMS is **0.321550 deg/s forearm** and **0.144005 deg/s paddle**;
both pass the existing 1 deg/s check with adequate hold coverage.

There are no recorded invalid packets/IMU samples, saturation, read failures,
recovery attempts, skipped acquisition deadlines, device queue drops/errors/retries,
send failures, disconnects or reboots. The loose-connection failure and earlier
bad startup gyro correction do not appear in this recording.

Each node misses **25 incoming samples** (50 total), in blocks of five or ten.
These losses occur around **75.3, 135.4, 195.6 and 255.7 s**, outside every requested
motion/history/ending quality context. They are not silently filled. Finalized
incoming delivery is **99.961539% forearm**, **99.962122% paddle**; still-open final
chunks are excluded from those percentages. All **131,438 received raw inputs**
are preserved once in the full reference.

All **22 quality contexts are clean**: both valid original streams, full coverage,
no source gaps, invalid/partial/unknown input or timestamp discontinuity in those
contexts. This includes the substituted mixed cue as a clean recording of the
actual movement. Clean data alone does not establish the requested action was
performed, hence the separate operator note and targeted confirmation.

## First close pair: automatic window warning explained

The automatic report lists 21 active cue windows out of 22 and flags successive
cue 1. This is separate from the user's mixed-cue substitution.

- First underhand cue: **257.729752 s**.
- Automatic first-cue activity cutoff: **258.473852 s**, 0.25 s before cue 2.
- Detector starts: **258.572590 s**, **0.842838 s after cue 1** and
  **0.151262 s before cue 2**.
- Second cue: **258.723852 s**.

The motion trigger therefore falls approximately 99 ms after the deliberately
short first-cue audit window ends, while still preceding the second cue. The raw
features show increasing motion energy before that trigger. Capture **21** retains
the close pair with **294.9495 ms history** and a normal ending at **261.827603 s**.
The independently extended context from cue 1 minus 300 ms through that capture's
ending contains continuous valid paired inputs and known decisions, without loss.

This evidence explains the automatic cutoff warning; it does not demonstrate a
lost whole pair. It is not a measured physical response/onset latency, nor proof
of an independently detected segment for every physical action. The three close
pairs share captures 21, 22 and 23 as permitted. No threshold, timing parameter,
automatic summary or cue-window rule is changed to force a passing report.
A repeat of the close pairs is not requested based on this evidence.

## Motion, history and available-data preservation

Gentle, compact, normal and quick isolated actions all have associated recorded
activity. The three compact wrist actions in the still-background phase are
captured; the remaining untested variation is compact wrist during stepping.
Mixed cue 3 has associated activity for the substituted larger movement.

Ordinary sway has zero protected activity in this run; footwork has approximately
**33.74%** protected activity. That extra footwork capture is accepted. Neither
percentage is a stroke-classification metric or a target used to tighten the gate.
The final five seconds of stillness contain **1,000 known-background frames**,
with zero active/unknown decisions, confirming an ending after mixed activity.

All **29 captures close normally** on confirmed background, with no in-capture
partial/unknown/discontinuity or truncation. All **12,980 required active/unknown
frames** are preserved. History high-water is **61/256** with zero evictions.

Twenty-seven captures have approximately **295–300 ms** history. Background
captures **2** and **5** have shorter history (89.925 and 265.0495 ms), explicitly
clipping **41** and **6** previously output frames. Overlap clipping avoids duplicate
output; those earlier records remain linked/preserved. No unexplained short
history is recorded. All 43 fallback sample records are forwarded, including
available-source evidence outside motion segments.

All **14,759 offered records** arrive unchanged at the independent local receiver:
**14,689 sample rows and 70 events**. Wire bytes/hash and the complete application
receipt match. There are no missing, changed, unexpected, duplicate/reordered
selected-output records, source-to-offer/history/detector replay mismatches or OR
safeguard violations. Queue high-water is 72/1,024 records and 119,874/4 MiB;
maximum queue age is 51.2622 ms, not physical end-to-end latency.

No further throughput/buffering investigation is added. This preserves the existing
Wi-Fi development evidence; final BLE integration remains subsequent work.

## Decision and targeted JCP5a

1. Accept the supported motion/data/history findings of this run, with the operator
   note and original automatic warning retained. Do not repeat the whole routine.
2. Confirm **only compact wrist rotation while gentle side-stepping**, three explicit
   cues. JCP5a uses the same firmware/settings and normal fresh startup/attachment/
   reference flow, followed by ten seconds of stepping preparation, 30 seconds
   containing three compact wrist cues and a still ending. **103 timed seconds**
   total, including initial supported hold and drain.
3. Read `JCP5A_TEST_GUIDE.md` and run `python -B .\run_jcp5a.py`. No USB repeat,
   large swing, new detector/transport tuning or reflash is needed. Background
   activity may already be present during steps; review raw/reference/contribution
   data together with the cues rather than claiming independent recall from activity
   alone. Keep motion small instead of enlarging it to force detection.
4. Review JCP5a alongside this run before freezing the air-motion detector and
   fixed tunables. Startup gyro bias and ready reference remain session-specific.
   No automatic freeze or BLE migration is authorized by returning test data.
   Actual ball contact remains outside these air-motion tests.

The user explicitly allowed a smaller JCP5a if needed. It is implemented as separate
files without altering the original final-trial runtime or data. Six targeted
tests and the inherited 17 final-motion tests pass; evidence is under
`validation/jcp5a-new-tests.log` and `validation/jcp5a-inherited-motion-tests.log`.
The previous broader suite's known queue-depth timing assertion limitation remains
documented; this increment does not modify that test or expand transport work.

## Reproduction and preservation

JCP3, JCP4a and the final-trial reports reproduce **exactly**. All JCP4b results
also match; its replay inventory alone adds the hash of the later-created derived
`jcp5_final_summary.json`. The audit verifies/removes only that extra inventory
entry for comparison. Original reports retain `needs_review` and their warnings.

All **76 original capture files** and **149 original final-trial runtime/config/
firmware/test/provenance files** match their saved hashes. The user note is saved
only under this review. Existing checkpoints and BLE/forearm implementations are
untouched. Reproduce from `CG4002_two_node`:

```powershell
python -B .\reviews\jcp5_final_20261028_135030\analyze.py --recompute
```

Without `--recompute`, the audit verifies already-reproduced reports plus original
hashes, gaps/health, the extended first-pair context and exact selected receipt.
Outputs stay under this review directory. Original final implementation remains
at `checkpoints/JCP5_final_air_motion_20261028`; new review/targeted source checkpoint
is `checkpoints/JCP5a_compact_stepping_20261028`.
