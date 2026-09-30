# Investigating the Wi-Fi send failures

> Historical diagnostic revision. The subsequent A/B captures recorded errno 12
> (`ENOMEM`) in both receiver modes. The active sketch now uses protocol v4,
> batching and bounded retries. Follow [the reliability test guide](TRANSPORT_RELIABILITY_TEST_GUIDE.md)
> for the next flash/test; the "no retries" description below describes the older
> diagnostic firmware, not the current implementation.

## Evidence, not yet a root-cause diagnosis

The 18:46 capture delivered 3,025/3,025 movement samples at the same nominal
200 Hz as the 19:27 capture. The latter acquired 38,001 samples over about 190
seconds with zero skipped scheduling slots or acquisition-buffer drops.
That does not support an unconditional "200 Hz is too fast" diagnosis.

The failing run attempted 5,035 movement sends: 825 failed locally, 4,210 were
accepted, and 4,198 were captured. Twelve additional accepted packets were not
captured. All 41 sends in burst 14 failed. Calibration/configuration remained
verified. The operator reports no intentional hotspot, distance or battery
setup change between runs.

Reconstructing sample formatting gives roughly 190 payload bytes per movement
frame, or 38 kB/s at 200 frames/s, excluding protocol/radio overhead and
diagnostics. Short-term queues and radio conditions matter even when average
payload bandwidth is small.

The installed Arduino ESP32 3.3.11 `NetworkUDP::endPacket()` uses lwIP `sendto()`
on a nonblocking socket. The old firmware retained only success/failure, not
errno. Espressif documents that UDP sends may return `ENOMEM` when driver TX
buffers fill: [lwIP limitations](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-guides/lwip.html#limitations).
This is a hypothesis, **not an error code observed in the old capture**, and
does not necessarily mean all application heap is exhausted.

## What changed

The diagnostic firmware keeps 200 Hz acquisition, calibration, filtering,
movement thresholds, v3 sample payloads and the destination unchanged. It uses
the same lwIP `sendto()` primitive directly, capturing errno before logging or
other API calls can alter it. No installed Arduino libraries were edited.
This is a diagnostic transport revision, not a confirmed fix for the old run.

There are no retries, deliberate sample omissions, batching, per-sample serial
prints or blocking retry delays. One movement frame still has one send attempt.

A cumulative `transport` JSON report is added once per second. It contains:

- Failure stage and exact errno; data versus diagnostic failures.
- Failure uptime, Wi-Fi state at failure, cached RSSI and its age, free heap.
- Current RSSI, free/minimum heap, disconnect count and latest reason/time.
- Failure categories: ENOMEM, would-block/no-buffer, network, other.

The receiver retains reports in `diagnostics.jsonl`, `summary.json` and readable
log output. The dashboard now shows **attempted → accepted → received** for
closed, consistent bursts, with the percentage based on attempted samples.

The report has a small cost; verify the measured timing again. Its snapshot
precedes its own send, so failure of that report appears in a later successful
one. Complete disconnection can prevent diagnostics from arriving at all.

## Next test: same firmware, two receiver modes

1. Stop all receivers and flash the updated sketch and sibling files once in
   Arduino IDE. Keep the existing board target, correct hotspot/laptop IP,
   200 Hz setting and movement thresholds.
2. From `CG4002_final_project`, start the console receiver:

   ```powershell
   python wifi_receiver.py --power-source lipo-usb-disconnected --notes "transport A: console, 200 Hz"
   ```

3. Disconnect USB and reset the LiPo-powered node. Keep it flat through
   calibration. Run for 60–90 seconds after calibration: ten seconds still,
   several short movements with pauses, one roughly ten-second continuous
   movement, then ten seconds still. Stop with Ctrl+C.
4. Start the dashboard receiver, with no other receiver running:

   ```powershell
   python CG4002_hardware/demo_receiver.py --power-source lipo-usb-disconnected --notes "transport B: dashboard, 200 Hz"
   ```

5. Reset the same node and repeat the same sequence/duration and physical setup.
   Finish still and stop with Ctrl+C. Switching receiver modes needs no reflash.
6. Share the two new capture folder names. If results differ, repeat in reverse
   order before assigning cause; one handheld A/B pair is not fully controlled.

The first reflash **is required** to add these measurements. Both receivers save
new folders automatically. The above commands assume the project-root terminal.

## Interpreting the next capture

- **ENOMEM:** allocation/driver-buffer pressure occurred. Check heap, signal and
  disconnect history; ample free heap does not rule out a full driver queue.
- **Would-block/no-buffer category:** preserve the exact errno to distinguish
  EAGAIN/EWOULDBLOCK from ENOBUFS.
- **Network errors/disconnects:** inspect the exact errno, reason and timing.
- **Format/not-ready/short-send:** investigate construction or socket setup.
- **Accepted but unreceived:** investigate receiver/network capture loss
  separately; sending-API success never guarantees delivery.

RSSI is sampled approximately once per second; its cached age is explicit.
Error/reason numbers come from ESP32, not Windows. No voltage/current measurement
is added, so this cannot establish or rule out a battery/power issue.

If send pressure is confirmed, batching or a bounded nonblocking retry queue can
be tested while retaining 200 Hz acquisition. Blocking the sampling loop is not
part of this diagnostic revision. Any retry implementation must define final
failure and duplicate accounting before it can support a delivery claim.

## Compatibility

The updated receiver reads old v3 captures, with transport diagnostics explicitly
unavailable. Update the receiver together with the firmware: the earlier receiver
rejects the new `transport` message type. Historical captures are unchanged.

Run `python -B -m unittest discover -s tests -v` from the hardware folder for
software regression checks. Compilation/tests are not a physical validation;
the root cause remains unconfirmed until the new hardware capture is reviewed.
