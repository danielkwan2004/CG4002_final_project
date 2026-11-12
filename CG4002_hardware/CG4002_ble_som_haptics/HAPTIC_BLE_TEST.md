# BLE haptic confirmation

## Flash

Open `CG4002_ble_som_haptics.ino` in Arduino IDE. Use FireBeetle 2 ESP32-E,
the correct COM port, and upload speed 115200. Libraries remain
NimBLE-Arduino 2.5.1 and ArduinoJson 7.x, ESP32 core 3.3.11.

`NodeConfig.h` defaults to `SOM_FOREARM` in this copy. Flash the forearm pod.
If also updating the paddle, unplug the forearm, select `SOM_PADDLE`, flash the
paddle, then return the source setting to your desired role. Each flashed board
keeps its own identity. The paddle rejects motor commands with `no_motor` because
only the forearm has a motor. Do not swap the stored calibration coefficients.

Wiring remains GPIO25 to the existing driver's IN, 3V3 to VCC and shared GND.
Use the existing driver module between GPIO and motor, as in the working build.

## First: motor alone, without a BLE client

1. Power on supported and completely still through gyro calibration (~2 s after
   startup). Open Serial Monitor at 115200. Wait for STREAMING.
2. Send `1`, wait 2 s: feel one pulse. Send `2`, wait 2 s: feel two pulses.
   Send `3`, wait 2 s: feel three pulses. Each pulse is 150 ms at full duty.
3. Send `d` and save the output. Confirm no new IMU failures or resets.

## Next: existing teammate BLE client

1. Connect, encrypt and subscribe to the existing notify characteristic; perform
   the existing handshake. UUIDs, lowercase name `forearm`, MTU185 and all sensor
   packet layouts remain the same. Complete the usual ready-reference routine
   if also checking motion-selected sensor output.
2. Write a complete JSON command to the existing encrypted WRITE characteristic:

```json
{
  "type": 12,
  "timestamp": 1234567890123,
  "session_id": "4e31d2b643344e77852a34262783a091",
  "sensor_session_id": "1234567890abcdef1234567890abcdef",
  "haptic_seq": 1,
  "result_seq": 34,
  "sensor_seq": 56,
  "pattern": "single"
}
```

   `12` is `HAPTIC_CMD` (0x0C); the timestamp is supplied by the client, e.g.
   `time.monotonic_ns() // 1_000_000`. Replace IDs/sequences with actual values.
   It is client metadata, not a scheduled board timestamp. The motor acts when
   its turn in the local queue arrives. Fields other than type/pattern are
   accepted without requiring a clock conversion.
3. Expect JSON `{"type":13,"status":"OK"}` (0x0D), then one felt pulse.
   Repeat with `double` and `triple`, incrementing haptic_seq, 2 s apart.
   ACK means accepted for playback; it does not measure motor operation.
4. Send `single`, `double`, `triple` rapidly: expect all six pulses in that
   order, grouped 1/2/3. Patterns run sequentially with at least 100 ms off
   between patterns. Four patterns can wait behind the active pattern.
5. Send `Double` or omit pattern: expect `status: ERROR`, `reason:
   invalid_pattern`, and no new pattern. Saturating the waiting queue returns
   `reason: busy`. Sending a valid pattern to paddle returns `reason: no_motor`.
6. Start a triple and disconnect/unsubscribe during it: the main loop turns the
   motor off and discards pending patterns. Reconnect with the usual handshake;
   old patterns must not replay.
7. While recording motion, repeat 1/2/3 commands and gentle movements. Send `d`
   before and afterwards. Return both health snapshots, BLE sent commands and
   received ACKs, and your observed pulse counts. Motor vibration can itself be
   visible to the IMU; note any associated extra motion segments. No detector
   thresholds or suppression intervals were added for haptics.

## Long JSON writes matter

The full payload is often larger than MTU185's 182-byte ordinary write payload.
Keep the existing MTU negotiation and use the client's supported ATT long write
(prepare/execute, write with response), or an already-supported larger negotiated
MTU. Send one complete JSON value to onWrite. Do not split it into independent
JSON fragments: no application-fragment protocol was added. The local command
buffer is 768 bytes including terminator; the characteristic's default GATT value
limit is 512 bytes. The supplied example fits that limit. If minimal commands
work but full commands do not, inspect this write path with the communications
teammate before changing sensor firmware.

There is no application-level de-duplication: submitting the command again is a
new request. Notification retries alone do not restart a pattern. The client
should avoid blindly resending an already accepted haptic_seq.

LiPo testing uses exactly the same BLE procedure. If USB is absent, client ACKs
and your pulse observations provide the first evidence; serial counters can be
checked in a later USB run. No USB connection is required for motor playback.
