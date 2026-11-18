# Pod confirmation review — 2026-11-01

**The observed IMU function, corrected sampling timing and forearm haptic command
execution pass. No repeat of movement/haptics is needed. Paddle startup repeatability
has only partial evidence; two extra reset holds would complete the requested check.**

Paddle: paddle_20261101_233805_230926. Final-boot counters5205/5205 successful reads,
0 failures/invalids/saturation/skips. Reported rates200.000–200.010Hz; observed
acquisition interval extrema4933–5066us.548 printed sample rows. It is already
ready before the deliberate reset, then identity/readback at0x68 verifies correctly
after that reset. No initial unready state occurs in this capture. All axes change
with movement; lifetime peak norm12.885g and gyro norm906.336deg/s are recorded
without clipping/invalid codes. Those unlabelled motion peaks are not a static
calibration result and do not alone indicate corruption.

Forearm: forearm_20261101_234051_396003. Final counters7444/7444 successful reads,
0 failures/invalids/saturation/skips. Reported rates200.000–200.004Hz. Across all
observed timing epochs, extrema4961–5043us (the final summary covers the epoch
after manual reinitialization).553 printed sample rows. Seven pulse commands
1,1,1,3,2,3,2 each complete without read failure or reset. One r command causes
successful IMU reinitialization. There is no captured ESP boot in this run; logging
begins with healthy acquisition already running. The command4 is unsupported and
was not forwarded as a motor command. No error arises from it.

Both nodes report zero serial sample prints skipped, and no logger errors. This
confirms the UART-buffer correction restored the target acquisition cadence in
these observed runs. Printed rows are intentionally20Hz; the200Hz evidence comes
from device acquisition timing/counters, not the number of printed lines. It is
not evidence of actual BLE received throughput.

No marked stationary/orientation periods exist, so this is not a calibrated
accuracy or complete physical connection certification. Physical motor operation
was confirmed by the user during the earlier pulse/continuous tests; current
logs add repeatable software and IMU-coexistence evidence. The earlier paddle
unready state remains unexplained, but is not reproduced here.

**Optional final closure of the earlier startup question:** with the paddle logger
open, RESET, support still10s, send d; repeat once more, then quit. Save the whole
folder. If ready=false occurs, send d BEFORE resetting again to capture the retained
error. Do not repeat the full movement/haptic routine or change any parameters.

Raw files and original automatic summaries are preserved unchanged. Detailed
measurements/source differences are in review.json; CAPTURE_SHA256.json inventories
all original files. Production firmware and parameters were not changed.
