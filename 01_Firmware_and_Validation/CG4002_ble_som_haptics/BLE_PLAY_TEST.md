# BLE-P1: first hardware motion test

Use the existing BLE client with your communications teammate. This checks motion
capture and the forearm/paddle OR/null behavior. Stroke names describe physical
actions only. Extra background capture and multiple segments for one action are
acceptable. There is no stroke-classification requirement.

## Before starting

1. Flash PADDLE, unplug it, select FOREARM, and flash the forearm, following README.md.
   Both use CG4002_ble_som.ino with only the NodeConfig.h role changed.
2. Stop the BLE client. Power both boards OFF. Disconnect USB if you prefer LiPo.
3. Support both boards/paddle motionless, then power ON. Wait at least 5 seconds
   without touching them so startup gyro calibration finishes. No flat/+Z pose
   is required because the reviewed accelerometer calibration is stored.
4. Attach the forearm pod in its usual orientation and hold the paddle. Start the
   existing client only when attached. Have your teammate save the received
   timestamped source0 batches AND combined SENSOR_DATA JSON if available, including
   connection/sync/disconnect messages. Keep the normal CONFIG continuous=true.
   Disable any automatic source1/DUMMY capture during this normal-stream test.
5. Gently sway in your natural ready stance while connecting. Once BOTH nodes
   finish the usual handshake/sync, continue that same gentle sway for 30 seconds.
   No steps, intentional wrist actions or swings. Source0 silence initially is
   expected: each board settles 10 seconds and fits its 12-second ready reference.
   Serial optionally shows `[motion] READY`; send `d` if uncertain.

The optional prompt script starts at step5 AFTER both nodes have finished sync:

```powershell
python -B .\play_test_prompts.py
```

It opens no BLE connection, so it can run beside the existing client. It saves
operator cue times and notes under captures/ble_p1_*. Your teammate still records
actual BLE data. Enter pauses allow time to rearrange the hardware without a rush.

## Actions after the30-second reference period

1. **Still â€”10 seconds.** Stand comfortably still. After pending data drains,
   expect no new normal SENSOR_DATA. Tiny body movement can trigger occasional
   output; note it, but do not tighten thresholds during this first test.
2. **Paddle alone.** Remove/support the forearm pod on a stable surface, leaving it
   powered. Hold the paddle in your hand. Wait8 seconds after setting things down.
   Over24 seconds, at seconds 4, 11, 18, make one comfortable small paddle rotation
   out and back, approximately 1 second. Keep the supported forearm pod untouched.
   Expect valid paddle values. A silent forearm should appear as six nulls in
   combined output. Do not substitute six zero values.
3. **Forearm alone.** Put the paddle down on stable support and keep it untouched.
   Reattach the forearm pod. Wait8 seconds. At seconds4,11,18 of the next24 seconds,
   make one gentle forearm lift/rotation and return, approximately 1 second.
   Expect forearm values and six paddle nulls once handling data drains.
4. **Compact wrist with both worn/held.** Take the paddle and keep the forearm pod
   mounted. Wait10 seconds to settle. At seconds4,11,18 over24 seconds, make one
   SMALL wrist rotation out/back, approximately 0.5 second, with forearm near ready.
   Do not exaggerate to force detection. Paddle-only or both-node output is valid.
5. **Comfortable normal motions â€”24 seconds.** Cues 4/11/18: one underhand, one
   backhand, one overhand movement, each out/back approximately 1 second. Rest in
   ready position between cues. We want useful motion data for every action;
   neither simultaneous node triggering nor a single segment per action is required.
6. **Background footwork â€”15 seconds.** Gentle left/right side steps without
   intentional paddle actions. Extra captures are acceptable; note their frequency.
7. **Wrist motion while stepping â€”24 seconds.** Continue gentle side steps.
   At seconds 4/11/18 make one SMALL wrist rotation out/back, approximately 0.5 second,
   then continue the same stepping. Use the specified wrist action for all 3 cues.
8. **Final still â€”12 seconds.** Stop steps and wrist motion. Allow history/live/
   ending batches to drain. Normal motion output should settle to silence.

Timed activity including reference/settling: **213 seconds (3 min 33 s)**, plus
startup and three Enter setup pauses. No ball contact or aggressive impact for
this first BLE check. Prefer LiPo to keep cables out of the way.

## What to return

Return the prompt folder and your teammate's saved BLE/combined JSON logs. If those
logs cannot be exported, record for each stage whether data appeared, whether
forearm/paddle nulls were correct, whether any cue was missed, and whether data
stopped after final still. Note the exact wrong/missed cue rather than repeating
silently. If using Serial, save `d` output from each board after the test.

We will inspect motion coverage, correct source identity/units, histories retaining
old timestamps, no stale counterpart data, clean stopping and sensor/queue health.
This script cannot infer missed readings during intentional silence from the
unchanged packet alone; source timestamp gaps and device health remain relevant.

If neither node sends: first check both are synchronized, subscribed and configured
continuous=true, and allow reference setup to finish. If armed stays false or
reference_failures grows, keep ordinary gentle sway and inspect Serial `d`; do not
change thresholds. If paddle/forearm labels are swapped, correct the flash role.
If a supported idle counterpart receives stale values instead of nulls, save the
log for your teammate to check the existing merger; do not change BLE UUIDs.

No need to repeat all CP/JCP experiments. Review BLE-P1 first, then choose any
small follow-up needed before paddle/ball contact.
