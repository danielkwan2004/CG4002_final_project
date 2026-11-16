# Communications setup and operation

Run commands from the directory containing `comms/` unless stated otherwise.
This package supplies the laptop relay and shared utilities. Full-system operation
also requires the Ultra96 adapter, DPU server/model, sensor firmware and Unity app.
The supported interactive relay environment is macOS or Linux with Bluetooth LE. Use Python
3.12 for the laptop environment; the pinned dependencies require Python 3.10+
for the MQTT-only runtime. The target Ultra96 Python environment must satisfy
that requirement; its separately managed DPU server can run in `pynq-venv`.

## Data flow and entry points

```text
Sensors --BLE--> laptop relay --MQTT/TLS--> broker --> Ultra96 consumer
                                            ^              |
                                            +--- results/haptics
                                            |
                                            +--> phone: results
                                            +--> laptop relay --BLE--> forearm: haptics
```

The laptop relay is the BLE-to-MQTT gateway; there is no separate gateway program.

| Entry point | Purpose |
|---|---|
| `laptop/run_pipeline.py` | Real BLE relay; default is continuous `stream` mode |
| `ultra96/ultra96_comms_dpu.py` (separate AI component) | Real DPU adapter: motion-triggered 400 × 12 input, requires external DPU server |

Run one laptop relay and one DPU consumer at a time.

## 1. Install dependencies

```sh
python3.12 -m venv comms/.venv
source comms/.venv/bin/activate
python -m pip install -r comms/requirements.txt
```

**Explicitly activate the environment in every new terminal before running the
Python commands below:**

```sh
source comms/.venv/bin/activate
python --version
```

Create the environment only once; activation must be repeated in new shells.
Use `deactivate` when finished. The broker's Mosquitto commands do not require
Python environment activation.

On Ultra96, install `comms/requirements-runtime.txt` in the
communications Python environment and activate that environment before starting
the consumer. The DPU server may use its separate `pynq-venv`.
macOS Bluetooth access must be granted to the terminal running the relay. Linux
requires a working Bluetooth adapter and BlueZ service. The submitted operating instructions use stream mode.

## 2. Configure the broker and clients

Follow [broker/README.md](broker/README.md) to generate a CA/server certificate,
create MQTT accounts, enable the supplied `broker/acl`, and start Mosquitto on
TCP/TLS port 8883. The ACL grants each account only its required topic permissions.

Copy the template once, then edit it to match your broker accounts:

```sh
cp -n comms/.env.example comms/.env
```

| Setting | Used by / default |
|---|---|
| `BROKER_HOST` | All Python MQTT clients; defaults to `localhost` |
| `CA_CERTS_PATH` | All Python MQTT clients; defaults to `comms/broker/certs/ca.crt` |
| `USER_LAPTOP_CLI`, `PW_LAPTOP_CLI` | Laptop relay |
| `USER_ULTRA96`, `PW_ULTRA96` | DPU consumer |

All scripts load the same `comms/.env` relative to their source location before
reading settings. Exported environment variables override that file. Use an
absolute path for a custom CA location. A remote client needs the
broker laptop's Tailscale IP, matching the certificate SAN. On Ultra96,
`localhost` refers to Ultra96 itself, not the laptop. Copy only the public CA
to clients. The laptop relay may use `localhost` when its broker runs locally.

On Ultra96, set the broker laptop's Tailscale IP in `comms/.env`:

```dotenv
BROKER_HOST=YOUR_LAPTOP_TAILSCALE_IP
CA_CERTS_PATH=/comms/ca.crt
USER_ULTRA96=replace_with_existing_username
PW_ULTRA96=replace_with_existing_password
```


## 3. Verify the broker

Perform the publish/subscribe check in [broker/README.md](broker/README.md).
It uses Mosquitto CLI tools and needs no project simulators or validation files.
A successful check prints `fb/sensor/raw {"acl_check":"broker works"}`. It verifies broker transport,
not BLE acquisition, FPGA inference or phone rendering.

## 4. Prepare and run BLE hardware

Use the final firmware supplied. The relay expects two BLE nodes named
`forearm` and `paddle`,  with the UUIDs and binary batch layout in  [PACKET_REFERENCE.md](PACKET_REFERENCE.md).
The real firmware selects motion locally; idle sensors need not publish continuously.
Only the forearm has haptic feedback in the current hardware configuration.

For a pairing-only check, start the broker and both sensors, then the laptop
relay below. For full-system operation, also start the DPU server and consumer
as described in section 5.

```sh
source comms/.venv/bin/activate
python comms/laptop/run_pipeline.py --mode stream
```

| Option | Behavior |
|---|---|
| `--mode stream` | Continuous reception/publication; no keyboard listener by default |
| `--mode stream -g` | Initially paused; Space starts/stops a session after both nodes have fresh data |
| `-c` / `--clock-resync` | Disables periodic clock resynchronisation (historical flag naming) |
| `-v` | Shows DEBUG packets and latency diagnostics in the terminal |

The optional readiness gate requires both nodes connected and a sample acquired
within the last two seconds from each. Move both sensors before pressing Space.
Real firmware selects motion locally, so idle time need not produce samples.
Use ordinary stream mode for headless operation. Ctrl-C stops the relay and
releases BLE connections.

The relay synchronises node clocks, pairs samples within 2.5 ms, and waits up to
1,000 ms (1 second) when a partner buffer is empty. This is a maximum wait for
delayed batches, not a fixed delay: available matching pairs publish immediately.
Unmatched samples are published with the missing sensor set to `null`; no data
is fabricated. Late samples that would move a source's published timestamps
backwards are discarded. The DPU requires complete pairs.

The 1-second default was selected by replaying laptop logs.
Replaying logged arrivals and clock offsets through the synchroniser
preserved the same complete pairs at 2,000, 1,000 and 750 ms. One second retains
additional margin. Replay approximates task scheduling; verify pairing during
the next hardware session.

## 5. Deploy the DPU consumer

Deploy the Ultra96 component (`ultra96/`), together with the same
`utilities/`, `requirements-runtime.txt` and a configured `.env`
under a common `comms/` directory on Ultra96. Install the runtime dependencies in
its Python 3.10+ environment and copy the public CA. Set the reachable broker
host and absolute CA path in that `.env`.

### Network connection using Tailscale

1. Install Tailscale on the broker laptop and Ultra96 using the
   [official installation instructions](https://tailscale.com/download).
   Sign both devices into the same tailnet and keep Tailscale connected during
   operation. The tailnet policy must allow Ultra96 to reach the laptop on TCP 8883.
2. Find the laptop's Tailscale IPv4 address in the Tailscale app/admin console,
   or run `tailscale ip -4` on the laptop if its CLI is available.
   Our deployment uses `100.110.160.69`; substitute your own laptop's address.
3. Set `BROKER_HOST` on Ultra96 to that address. Keep the actual absolute
   `CA_CERTS_PATH` and existing MQTT credentials.
4. Start Mosquitto on the laptop with `listener 8883`, as shown in the
   [broker guide](broker/README.md). Do not restrict this listener to
   `127.0.0.1`; allow incoming TCP 8883 through the laptop firewall from the
   intended Tailscale clients. The broker certificate must include the laptop's
   Tailscale IP as an IP Subject Alternative Name.
5. On Ultra96, run `tailscale status` and
   `tailscale ping YOUR_LAPTOP_TAILSCALE_IP` to check peer connectivity.
   Then perform the broker guide's MQTT check using that address and the local
   CA path. A successful Tailscale ping alone does not verify MQTT/TLS access.

MQTT connects to the broker over Tailscale; no reverse SSH tunnel is required.
Ordinary SSH can still be used to start/stop programs on Ultra96. The DPU Unix
socket remains local to Ultra96 and is unaffected by this network configuration.
See [Tailscale device connections](https://tailscale.com/docs/how-to/connect-to-devices)
for service access over the tailnet.

Start the external `dpu_server.py` in its FPGA/PYNQ environment first, then:

```sh
# Activate the communications Python environment in this terminal.
# If it was created at comms/.venv:
source comms/.venv/bin/activate
python comms/ultra96/ultra96_comms_dpu.py
```

The adapter logs an error and returns if the socket is absent. The server and trained
model/FPGA artifacts are not supplied in this checkout, so their deployment
instructions are required from the AI component documentation.

## 6. Connect the phone and verify feedback

Use the complete Unity project supplied, including its scenes and dependencies.
Place the broker's public CA at `Assets/Resources/ca.crt.txt` in that project,
rebuild, then enter the reachable broker host and phone account in the app. It uses
TCP/TLS 8883. If the phone connects to the broker's Tailscale IP,
it also needs Tailscale connectivity and permission to reach that port.

AI Results travel on `ultra96/ai/results`; haptic feedback travels on
`ultra96/ai/haptics` and is relayed to the forearm. Firmware accepts `single`,
`double`, `triple`; an ACK means accepted for playback, not measured vibration.
The laptop forwards haptic commands at most once every 2 seconds, keeping only
the newest pending command during the wait. Sensor streaming continues.

For an end-to-end check, confirm the relay and consumer connect to the broker,
select handedness on the phone, and perform strokes with both sensors. Check
`[SYNC STATS]` for complete pairs and the consumer logs for accepted predictions;
confirm the phone displays those results. DPU results depend on sufficient input,
motion detection and confidence filtering, so every movement need not yield one.
Stop the relay and consumer with Ctrl-C when finished.

## Diagnostics and verification

Logs are written under `comms/logs/` regardless of working directory. Laptop
logs use `logs/laptop/`; consumers use `logs/`. DEBUG records are always saved.
Check `[SYNC STATS]` for matches, singles and late drops. `[LATENCY]` measures
round trips, not inference delay, motor completion or screen rendering.

MQTT reconnects with backoff up to 15 seconds and restores subscriptions.
New publishes while disconnected are dropped; in-flight QoS 1 messages can be
redelivered. BLE setup retries discovery/handshake/synchronisation automatically.

| Symptom | Check |
|---|---|
| CA/configuration error | Absolute CA path, file permissions and `.env` values |
| TLS hostname failure | Broker SAN, chosen hostname/IP, clock and certificate expiry |
| MQTT auth failure | Correct account variable pair for the selected script |
| MQTT connected but messages missing | ACL username and topic permissions; production broker restarted with the ACL |
| No BLE node | Board role/name, power, Bluetooth permission and another connected central |
| No sensor publication | Optional session gate, firmware calibration/reference and motion |
| Many singles/late drops | Both boards, clock alignment and BLE delivery; inspect serial logs |
| No DPU results | Server/socket, handedness, complete 400-pair windows and confidence filtering |
| No physical haptics | Real firmware, forearm driver/motor, accepted pattern and cooldown |

See [PACKET_REFERENCE.md](PACKET_REFERENCE.md) for field layouts and routes.
