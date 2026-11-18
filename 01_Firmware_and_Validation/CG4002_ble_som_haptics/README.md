# Hardware motion detection plus BLE-controlled haptics

Open **CG4002_ble_som_haptics.ino**. This is a complete copy of
`../CG4002_ble_som`, extended for the new incoming haptic command. The original
folder is preserved. Flash/test instructions: **HAPTIC_BLE_TEST.md**.

## Configuration and behavior

- Select FOREARM/PADDLE in `NodeConfig.h`; this copy defaults to FOREARM.
- `HapticsConfig.h` holds GPIO25, enable-by-role, duty, pulse/gap times and queue size.
- Exact lowercase patterns: `single`, `double`, `triple`.
- Existing 150 ms full-strength ERM pulses are retained: double gap250 ms,
  triple gaps100 ms; separate queued patterns have100 ms off between them.
- Four waiting patterns plus one active; queue overflow returns ERROR/busy.
- Playback advances in the main loop without delay(), leaving sensor sampling active.
- Disconnect/subscription transitions cancel active and queued feedback.
- Valid forearm requests retain the existing type13/statusOK ACK. Invalid pattern,
  absent motor and full queue produce type13/statusERROR with a short reason.
- New session/sequence/timestamp fields are accepted as metadata; host time does
  not schedule playback. The payload's type must serialize to integer12 (0x0C).
- Only the forearm has a motor by default. Send feedback to the forearm connection.
- Full JSON uses an enlarged command buffer. See the long-write requirement in
  the guide; do not divide a JSON command across independent ordinary writes.

BLE names/UUIDs, security, MTU request, sync clock, six-axis units and binary
sample format are retained. Motion features, calibrated profiles, alpha0.2,
200Hz acquisition target and300ms history remain as copied. No Wi-Fi added.
A haptic may be visible as real acceleration; motion gating remains unchanged.

## Validation records

`VALIDATION.json` records THIS extension. `BASELINE_VALIDATION.json`, copied
checkpoints and the pre-existing build/native logs are inherited evidence for
older firmware. New logs use `haptics_` names and build folders use
`build_haptics_`. The source manifest `HAPTICS_SOURCE_CHECKPOINT.json` records all
original files before the clone. No firmware was flashed by the agent.

Run native tests for both roles:

```powershell
cmd /c .\tests\run_tests.cmd
cmd /c .\tests\run_tests.cmd C:\Users\USER\Documents\Arduino\libraries\ArduinoJson\src 2
```

Original motion-test prompts are copied for reference. Their directory/sketch
names refer to the original motion-only checkpoint; use this sketch and the new
haptic guide for the current extension.
