# Battery-powered IMU over BLE

The folder name is retained for Arduino compatibility, but this sketch now uses
BLE exclusively. Open imu_wifi_battery_test.ino in Arduino IDE. It contains
the working ICM-42686-P I2C acquisition code; the BLE.ino tab contains the
supplied BLE protocol and the only setup() and loop() functions. Arduino
builds both tabs together. Keep them in the same folder.

## Hardware and upload

- Board: FireBeetle 2 ESP32-E.
- IMU: ICM-42686-P, SDA on GPIO21, SCL on GPIO22, common GND, powered from
  FireBeetle 3V3. The sketch probes addresses 0x68 and 0x69.
- Use the same I2C wiring as the successful Wi-Fi test.
- Install **NimBLE-Arduino 2.x** and **ArduinoJson 7.x** through Library Manager.
- Set NODE_ID in BLE.ino to paddle or forearm, then upload.
- Disconnect USB and power the board through its LiPo connector. No USB Serial
  connection is required; Serial output is optional troubleshooting information.

## Laptop connection

Use the BLE client compatible with the supplied protocol. The earlier UDP
listen.py does not receive BLE notifications. No hotspot or IP address is
needed. The client must pair/encrypt the link, subscribe to notifications,
and perform HELLO, CONFIG, and clock synchronisation before streaming starts.

- Service: 25E2CCC3-D857-49A6-AFDC-F6895F1854B0
- Notify: 2F752BBE-B112-4F11-9789-093262B39116
- JSON write: A9A6FB55-B997-4A3B-A9FA-D97C1E23DB5F
- Control sequence: HELLO_REQ (0x01), CONFIG (0x03, continuous: true),
  SYNC_START (0x05), SYNC_REQ (0x06, request_id), SYNC_END (0x08).
- Firmware requests MTU 185. Full five-sample notifications require negotiated
  MTU of at least 166 (163 payload bytes plus ATT overhead).

## IMU readings

The sensor is configured for 200 Hz, +/-16 g acceleration and +/-2000 degrees/s
angular rate. The firmware polls data-ready and reads all six axes in one I2C
burst. Only fresh successful readings enter the BLE batches; failed reads
trigger IMU reinitialisation attempts every five seconds.

The supplied binary format is unchanged: three header bytes (0x09, count,
source), followed by count little-endian Python <II6f records:

1. Sequence number (uint32)
2. Host read timestamp in milliseconds since boot (uint32)
3. Accel X, Y, Z in **m/s^2**, including gravity (float32 each)
4. Gyro X, Y, Z in **degrees/s** (float32 each)

Axes use the sensor's native orientation. Values have scaling applied but no
bias calibration, so HELLO reports calibrated: false and includes imu_status.
At rest, acceleration magnitude should be around 9.81 m/s^2 and gyro readings
near zero, with normal bias/noise.

Continuous mode sends five readings per batch, approximately 40 notifications
per second. This replaces the old once-per-second Wi-Fi summary. A laptop
client can still print the latest values once per second while receiving all
batches. There is no guarantee of lossless sampling or delivery during delays
or BLE congestion; the bounded transmit queue retains the supplied drop policy.

The existing one-second capture command and source tags are retained. Source 0
is continuous; source 1 is the command-triggered capture formerly labelled
dummy. Both contain real IMU readings. When both are active, the same physical
sample is appended to both streams with the same timestamp and separate sequence
numbers; the sensor is still sampled at 200 Hz.

The actuator TODO and its existing protocol acknowledgement are retained, but
no actuator hardware action is implemented. That acknowledgement is not proof
of physical actuation.
