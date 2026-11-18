# BLE haptic extension - 7 November 2026

Work folder: CG4002_ble_som_haptics. Complete clone of CG4002_ble_som; source
folder must remain unchanged. All inherited evidence predates this extension.
Haptic commands are numeric type12 JSON on the existing encrypted write UUID.
Map exact lowercase single/double/triple to one/two/three proven ERM pulses.
Only forearm has motor, GPIO25 through existing3-pin driver. Default roleFOREARM.
Non-blocking main-loop playback, four waiting slots, ERROR on invalid/full/no-motor.
ACKtype13/statusOK means accepted, not physical completion. Preserve all sensor
calibrations, detector parameters, filter, acquisition and BLE connection protocol.
Accept full metadata-bearing payload, enlarged buffer; client must deliver complete
long JSON writes if greater than ATT MTU-3. No metadata scheduling or application
dedup. Disconnect/unsubscribe cancels playback. Do not suppress IMU around vibration.
Next hardware check: HAPTIC_BLE_TEST.md. Agent does not flash hardware.
