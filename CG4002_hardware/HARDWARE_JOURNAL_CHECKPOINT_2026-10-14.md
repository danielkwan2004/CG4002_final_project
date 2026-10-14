# Hardware Journal Checkpoint for Battery Operation and Forearm Pod Prototype

**Date:** 14 October 2026  
**Project:** CG4002 Pickleball Stroke Classification System  
**Checkpoint:** Working forearm sensor prototype with LiPo operation and movement-triggered Wi-Fi telemetry

## Progress at this checkpoint

I have established a working hardware baseline for the forearm sensor node. The FireBeetle ESP32 and ICM-42686-P IMU acquire and process six-axis motion data, detect arm movement, and transmit the corresponding readings to the laptop. The system now operates successfully with the LiPo battery and USB disconnected, overcoming the earlier situation in which I could only get the setup working with USB connected.

I have also completed the first 3D-printed enclosure pod for the forearm node and its IMU, with the required electrical connections attached. The assembled prototype is functioning and provides a practical starting point for further mechanical improvements. Separately, I have tested the second IMU intended for the pickleball paddle node and confirmed that it works well.

This checkpoint records the working configuration, the debugging completed, and the test evidence to refer back to before making further changes.

## Debugging the acquisition failure

During earlier testing, the node could complete calibration and enter `STREAMING`, but aggressive shaking sometimes caused it to enter `FAULT`. Once this happened, acquisition did not resume and I had to restart the hardware. This behaviour was unsuitable for a sensor intended to capture fast arm movements and pickleball strokes.

The code review identified a permanent fault latch: a single failed IMU read set `imuReadFault`, after which the main loop entered `FAULT` and stopped attempting further sensor reads. The firmware had no runtime recovery path. High acceleration or angular velocity did not directly trigger this fault; saturation was already handled through a sample status flag. The original Serial output did not identify what caused the first failed read, but the code explained why one failure could stop the system indefinitely.

I updated the firmware so that an isolated failed read is discarded and acquisition is retried at the next scheduled sampling slot. After 20 consecutive failed reads, the node enters a recoverable fault and attempts to reinitialize the I2C bus and IMU once per second. Streaming resumes after configuration verification and a successful sensor read. The valid startup calibration is retained, avoiding recalibration while the sensor may be moving.

I also added explicit fault reasons, read-failure and recovery counters, saturation counts, and a Serial health command. Sending `d` now reports whether acquisition is progressing and whether any failures have occurred. These diagnostics make future problems easier to distinguish from Wi-Fi delivery issues.

## Motion processing and transmission

The current implementation samples at a target rate of **200 Hz**, corresponding to one acquisition every **5 ms**. It uses accelerometer and gyroscope ranges of **±16 g** and **±2000 degrees per second**, with startup calibration and conversion into physical units.

A low-pass filter with **alpha = 0.2** smooths all six axes. A movement detector then evaluates the filtered acceleration and angular velocity to decide when to transmit. This combination effectively detects the tested arm movements while suppressing continuous transmission of stationary readings.

Movement begins when the filtered gyroscope magnitude reaches **40 degrees per second**, or the filtered acceleration magnitude deviates from gravity by at least **0.30 g**. Movement ends after both measures remain below their respective stop thresholds of **15 degrees per second** and **0.15 g** for **150 ms**. Using different start and stop thresholds prevents small fluctuations from repeatedly switching transmission on and off.

While movement is active, the node sends the six-axis readings through the temporary Wi-Fi telemetry link. When the sensor settles, it stops adding movement samples for transmission. Acquisition and filtering continue internally so that the next movement can be detected. Periodic diagnostic packets and any already-queued samples can still arrive after movement ends. The existing non-blocking haptic pattern support also remains available in the forearm firmware.

## Verification with USB and LiPo power

I performed separate Wi-Fi receiver captures with USB connected and with USB disconnected while operating from the LiPo battery:

- **USB-connected test:** approximately **200.002 Hz**, with **1,366 out of 1,366 movement samples received** across five completed movement bursts.
- **LiPo test with USB disconnected:** approximately **200.000 Hz**, with **1,269 out of 1,269 movement samples received** across the four movement bursts recorded during the capture.

Both runs remained in `STREAMING` and recorded zero IMU read failures, skipped sampling slots, buffer drops, or failed sends. The recorded movement samples had no duplicates or reordering. Checking the sample data also confirmed the six-axis low-pass filter behaviour and movement endings after approximately 150 ms below the stop thresholds.

The LiPo receiver was started after the node was already running. Its replayed summaries included five earlier bursts, so I used the receiver's `capture_delivery` results when assessing delivery during the actual recording window. This avoids incorrectly counting samples sent before recording began as packet loss during the test.

The results demonstrate successful motion acquisition and telemetry during the tested battery-powered operation. The previous fault did not recur in either run. Firmware compilation, C++ fault-injection tests, and 67 Python receiver regression tests also passed. Automatic recovery was exercised in software tests; the physical runs did not require it because no read failures occurred.

## First forearm enclosure prototype

Following the forearm enclosure direction in `HARDWARE_PLAN.md`, I have built the first 3D-printed pod for the forearm node and IMU. The components and their required connections are attached within the prototype, bringing the sensor assembly into an enclosed form suitable for continued forearm testing.

The prototype is complete and functioning as the current mechanical baseline. It gives me a physical reference for evaluating component placement, access to connections, mounting stability, and comfort during arm movement before producing the next revision.

> **INSERT PHOTO HERE — Completed first forearm enclosure pod, showing the node, IMU placement, and attached connections.**

*Figure 1. First 3D-printed forearm sensor pod prototype with the forearm node and IMU assembled and connected.*

I have additionally tested the IMU intended for the pickleball paddle node and confirmed that it responds correctly during testing. This provides a working sensor foundation for the paddle node as development proceeds.

## Work planned for the coming weeks

I will refine the 3D enclosure design to improve the fit, component arrangement, cable routing, accessibility, and comfort of the forearm pod. The current prototype will remain the reference when comparing changes to the enclosure and mounting arrangement.

I will also develop a more selective movement-detection algorithm. The current filtered threshold approach works as a baseline, but the next version should better distinguish meaningful stroke-related movement from sensor noise, small incidental movements, and other non-stroke activity. I will compare it against the current implementation to reduce unnecessary transmissions while retaining the useful beginning, duration, and end of each movement.

The selected motion data will subsequently be sent over **BLE** to the teammate responsible for hardware AI and stroke classification. The present Wi-Fi implementation provides the working acquisition and validation baseline for that integration. The aim is to supply relevant movement segments that support reliable stroke analysis without overwhelming the downstream system with unnecessary stationary or noise-dominated data.

## Checkpoint references

The configuration recorded here is **200 Hz acquisition, ±16 g acceleration, ±2000 degrees per second angular velocity, alpha = 0.2 filtering, and a 150 ms movement-stop quiet window**. This journal entry preserves the completed debugging and prototype milestone before the enclosure and detection algorithm are revised.

- Hardware implementation plan: `HARDWARE_PLAN.md`.
- Flashing and test procedure: `P1_P2_TEST_GUIDE.md`.
- USB capture evidence: `captures/p1_p2_20261014_075726_340289/`.
- LiPo capture evidence: `captures/p1_p2_20261014_080025_009689/`.

Each capture folder retains the sample CSV, diagnostic history, readable log, metadata, and summary used to verify this checkpoint.
