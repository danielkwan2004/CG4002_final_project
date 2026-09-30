# Verify buffered Wi-Fi delivery before the presentation

## Current status

The 20:02 console and 20:04 dashboard captures recorded `sendto()` errno 12
(`ENOMEM`). Sampling stayed at 200 Hz without skipped slots or acquisition-buffer
drops. The console lost 78/2,402 movement samples; the dashboard's **new** bursts
lost 96/1,953. Both used boot `a911ed8f`: historical summaries from the first run
inflated the second run's whole-boot missing count. Those captures are unchanged.

The subsequent 21:01 console capture (`p1_p2_20260930_210121_733771`, boot
`e9afc9c9`) delivered all 3,995 movement samples across seven bursts. The 21:03
dashboard capture (`p1_p2_20260930_210302_338359`, boot `dc87afc8`) delivered all
3,317 across five bursts. Both had zero socket errors, retries, final drops,
missing samples, skipped acquisition slots, and acquisition-buffer drops.
Their transmit queues peaked at 5/128 samples and 20 ms recorded age.

Those runs validate the queued transport in those conditions, not indefinitely.
They cover 56 and 45 seconds of acquisition. Console intervals ranged from
3.289 to 6.711 ms (99.18% within 4.5–5.5 ms); dashboard intervals ranged from
4.827 to 5.118 ms. Console long/short pairs align with the one-second diagnostic
boundary. The previous heartbeat sent several packets in a single loop without
an acquisition-headroom guard, making that scheduling a likely contributor.

The **current revision** staggers those diagnostics as described below. It needs
a fresh physical capture to verify timing; the successful captures above predate
this scheduling change. No previous evidence has been overwritten.

## What changed (protocol v4)

- Sampling, register settings, calibration, filters, and motion thresholds stay
  unchanged at a nominal 200 Hz.
- Movement samples enter a statically allocated **128-sample transmit queue**,
  separate from the acquisition buffer. At continuous 200 Hz it holds 640 ms of
  newly generated samples before filling if none can leave.
- A datagram contains up to **five complete sample rows**, at most 1,399 payload
  bytes. Five-sample batches reduce steady movement traffic to about 40 data
  datagrams/s, without dropping or averaging samples. Smaller batches flush after
  20 ms or at a burst boundary. Original timestamps and sample IDs are retained.
- A failed transient send (`ENOMEM`, would-block/no-buffer or connection-related
  errors) retains the exact datagram for another attempt, spaced at least 10 ms
  apart. Successful sends are spaced at least 2 ms apart. Each service invocation
  makes at most one nonblocking send; there are no blocking retry/sleep loops.
- The main sampling loop admits **at most one telemetry operation per acquired
  sample**, only with **more than 3.5 ms** until the next scheduled acquisition.
  This covers movement batches, final summaries, and heartbeat/configuration
  diagnostics. It is a cooperative guard, **not a hard real-time guarantee**:
  an unexpectedly slow operation can still overrun. FAULT reporting/draining
  remains available in 5 ms slots when acquisition has stopped.
- The one-second heartbeat is now a sequence of individual packets separated
  by at least **10 ms**, leaving intervening acquisition slots for movement
  delivery. Configuration is another scheduled packet, normally every five
  seconds. Startup configuration is sent before acquisition begins. Report
  parts snapshot their own current counters, so their `produced` values may
  differ; join using boot/type/report or burst identity, not exact snapshot time.
- Queue capacity and a **1,000 ms oldest-sample age limit** bound memory and stale
  backlog. Overflow, expiry, permanent failures, or defensive burst-history
  eviction are recorded as final drops, not hidden. A batch expires when its
  oldest sample reaches the age limit; younger samples in that batch expire too.
- Burst final counts are published only after the gate closes AND its pending
  samples resolve. Motion can be "Settled" while the queue finishes draining.
- Diagnostics remain best-effort UDP. Final burst summaries are sent promptly,
  remain dirty after a failed local send (attempts spaced at least 10 ms), and are
  also replayed by heartbeats. Other diagnostics are periodically repeated, not
  individually enqueued; diagnostic send failures remain visible.

The receiver expands each v4 batch into individual rows in `samples.csv`. It
still reads v3 captures. Update firmware and receiver **together**: an older
receiver cannot read v4. The optional `WIFI_ONLY_DEMO` bench mode is not this
queued IMU workflow; leave it false.

## Counters that must not be confused

`timing` and `burst`: `attempted` means unique samples offered for delivery, not
the number of socket calls. `attempted = accepted + failed + pending`. `failed`
is now a final local sample drop; a retryable send error alone does not increment
it. `closed=true` means the gate is closed and pending is zero.

`transport`: physical UDP-call attempts/errors, including retries and diagnostic
packets. These are **not unique sample losses**. `ENOMEM` may still appear while
all samples are subsequently recovered.

`txqueue`: unique offered/accepted/pending/final-drop counts, recovered samples,
retry calls, queue high-water/age, and final-drop causes. Recovered samples count
samples in a batch accepted after one or more failed socket calls.

`config.diag_scheduler = "staggered_v1"` identifies the scheduling revision;
`telemetry_headroom_us = 3500` records its guard. `timing.max_diag_us` records
the maximum scheduled diagnostic operation cost since boot (formatting and send,
excluding startup configuration). It appears as `max_diagnostic_us` in console
logs and `max_diagnostic_service_us` in `summary.json`. Missing on old captures
means **not measured**, not zero. `max_wifi_us` now includes diagnostic operations
as well as movement queue work; older builds did not time the whole heartbeat.
Measurements include a timing report's own cost only in subsequent reports.

UDP acceptance is not a laptop acknowledgement. The receiver still independently
checks unique received IDs and counts accepted-but-unreceived samples. Retries
here recover local send failures; there is no end-to-end ACK/retransmission
protocol for a packet accepted locally but lost later in transit.

## Current capture versus whole device boot

The dashboard and `[this-capture]` console line use `capture_delivery` in the new
summary. They exclude historical bursts and bursts already underway at the first
observed acquisition boundary. Exclusions and incomplete evidence are explicit;
they are not counted as lossless. Starting capture mid-burst cannot support a
full-burst delivery percentage.

`finalized_burst_totals`, device timing, and raw transport diagnostics remain
whole-boot/observed-history evidence. Error/recovery changes use a known zero
baseline if startup was observed from acquisition zero; otherwise they start at
the first received report. Loss before that baseline is not measured by those
deltas. The acquisition rate/count/range on the dashboard is labeled boot-wide.

## Flash and test

1. Stop other receivers. Reopen/upload the current `CG4002_hardware.ino` with its
   sibling source files using the existing FireBeetle ESP32-E board target. Check
   the hotspot and laptop destination IP are still correct. No package installs
   or changes to Arduino's installed libraries are needed.
2. From `CG4002_final_project`, start the updated console receiver:

   ```powershell
   python wifi_receiver.py --power-source lipo-usb-disconnected --notes "v4 staggered A: console, final 90s"
   ```

3. Disconnect USB, power/reset the LiPo-powered board, and keep it flat (+Z up)
   through calibration. Verify a new boot ID and `diag_scheduler=staggered_v1`
   in the console config line. Time **90 seconds after STREAMING starts**:
   - 0–10 s: remain still;
   - 10–30 s: shake/rotate/lift/lower, with pauses;
   - 30–45 s: continuous movement that keeps the gate active;
   - 45–60 s: several more movements, with pauses;
   - 60–90 s: remain still, allowing final summaries and several heartbeat
     cycles to arrive. Then Ctrl+C. Receiver runtime includes waiting and
     calibration, so it must be longer than 90 seconds.
4. Start the dashboard receiver (not simultaneously with the console receiver):

   ```powershell
   python CG4002_hardware/demo_receiver.py --power-source lipo-usb-disconnected --notes "v4 staggered B: dashboard, final 90s"
   ```

5. Reset the board again; **check that its boot ID differs from run A**. Repeat
   the same 90-second sequence. Keep the dashboard open during this run. The
   config marker is also saved in `diagnostics.jsonl` and `summary.json`.
6. Share both new capture folder names. Do not delete prior evidence. Optionally
   repeat a third capture without resetting the node to check that historical
   bursts are explicitly excluded rather than shown as new losses.

## What success looks like

- Verified IMU configuration; measured cadence near 200 Hz, no skipped slots and
  no acquisition-buffer drops.
- Verified `staggered_v1` config marker. Aim for all intervals within 4.5–5.5 ms
  and no recurring one-second long/short pairs. This is a validation target, not
  a promise of a perfectly periodic 5 ms clock. Inspect `max_diag_us` alongside
  all timing evidence rather than relying only on the average 200 Hz rate.
- Final `txqueue` pending = 0 and final drops = 0 (all four drop causes = 0).
- Every in-scope burst has final consistent counts; no unseen new bursts, no
  accepted-but-unreceived samples, and offered = accepted = unique received.
- Retries/ENOMEM may be nonzero if recovery succeeds. Report those honestly as
  recovered transient send errors, not as dropped samples or a perfect radio.
- If queue high-water approaches 128, expiry/overflow occurs, or timing worsens,
  do not declare the issue solved. Review that evidence before tuning limits.

## Software checks

From `CG4002_hardware`:

```powershell
python -B -m unittest discover -s tests -v
.\tests\run_tx_queue_tests.cmd
node tests/test_dashboard_render.js
```

The second command uses an existing Visual Studio 2022 C++ Build Tools install
to execute the **actual C++ queue and encoder**, with simulated 240/500 ms send
outages, sustained blockage, overflow/expiry, immutable retries, burst boundaries
and clock wrap. It builds in the system temporary directory and installs nothing.
It also compiles the actual `CaptureDiagnostics.cpp` with hardware/socket stubs
to check overlapping queued bursts, final-count publication, failed control-send
backoff, history eviction and expiry settlement.
Python tests cover v3/v4 parsing, delivery finalization, capture baselines, motion
ordering, and real localhost UDP traffic at a synthetic 200 Hz in both console
and dashboard modes. The optional Node.js test exercises the actual dashboard
renderer with a minimal DOM stub: historical counts, recovered errors and
pending samples. These checks do not emulate RF, hotspot behavior, power, or
the ESP32 Wi-Fi driver's timing.

Verification of the initial queue implementation: 63 Python tests passed, both native C++ test
executables passed, and the dashboard renderer check passed. Browser replay of
the original dashboard capture showed 1,953 offered / 1,857 accepted / 1,857
received and seven new bursts, with the historical seven explicitly excluded.
These are software/regression results, not new device measurements.

That initial sketch compilation also passed for `esp32:esp32:dfrobot_firebeetle2_esp32e`
with ESP32 Arduino core 3.3.11: 929,035 bytes flash and 82,116 bytes global RAM.
No device was flashed by the agent.

Staggered-diagnostics verification: 65 Python tests and both native C++ test
executables passed, along with the dashboard renderer check. Added C++ cases
cover the headroom guard, one telemetry operation per acquisition, fault-mode
slots, clock wrap, individual heartbeat packets, failed-control retention, and
18,000 samples delivered in order during a simulated 90-second run. Simulated
operation durations are test inputs, not measured ESP32 timing. The updated
FireBeetle ESP32-E build also passed: 929,647 bytes flash and 82,140 bytes global
RAM, using ESP32 Arduino core 3.3.11. No device was flashed by the agent.
Physical timing validation of `staggered_v1` remains pending the final captures.
