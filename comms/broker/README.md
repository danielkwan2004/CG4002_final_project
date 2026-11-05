# Local MQTT broker setup (macOS)

Run Mosquitto on the laptop to connect the sensor relay/dummy sender, Ultra96,
and Unity phone app. Python clients and the current Unity app use **MQTT over
TCP/TLS on port 8883**, with username/password authentication. The existing
configuration also enables secure WebSockets on port 9001; the current Unity
client does not use that listener.

These instructions use the existing certificates and broker configuration.
No FireBeetles or Ultra96 are needed for the local smoke test.

## 1. Install and locate Mosquitto

```sh
brew install mosquitto
```

Run the remaining commands from the repository root:

```sh
cd /Users/ven/Uni/cg4002/CG4002_final_project
export PATH="$(brew --prefix)/sbin:$PATH"
```

Adjust the repository path if your checkout is elsewhere. Repeat the `cd` and
PATH export in each new terminal. If Mosquitto is already installed, skip installation.

## 2. Check the existing configuration and certificates

The project expects:

```text
comms/broker/
├── mosquitto.conf
└── certs/
    ├── ca.crt          # Public CA certificate trusted by clients
    ├── server.crt      # Broker certificate
    ├── server.key      # Broker private key
    └── passwordfile    # Mosquitto password hashes
```

The existing directory also contains CA signing files. These are not required
on clients. Keep private keys and the password file on the broker/signing machine;
clients only need `ca.crt`.

Inspect the public certificate and verify its signature:

```sh
openssl x509 -in comms/broker/certs/server.crt \
  -noout -subject -dates -ext subjectAltName
openssl verify -CAfile comms/broker/certs/ca.crt \
  comms/broker/certs/server.crt
```

The certificate inspected for this guide includes `localhost`, `127.0.0.1`, and
`Venices-MacBook-Air.local`. It expires on 21 October 2027 UTC. Check your own
output if the certificates have been replaced.

Open `comms/broker/mosquitto.conf` and confirm that every `cafile`, `certfile`,
`keyfile`, and `password_file` points to an existing **absolute path** in this
checkout. The current file uses `/Users/ven/Uni/cg4002/CG4002_final_project/`.

For reference, the required TCP/TLS listener is:

```conf
listener 8883
cafile /absolute/path/to/comms/broker/certs/ca.crt
certfile /absolute/path/to/comms/broker/certs/server.crt
keyfile /absolute/path/to/comms/broker/certs/server.key
require_certificate false
allow_anonymous false
password_file /absolute/path/to/comms/broker/certs/passwordfile
```

`require_certificate false` means clients do not supply their own certificates;
they still validate the broker certificate and authenticate with a password.
The existing config also has the optional port 9001 WebSocket listener.

Certificates and `.conf` files are ignored by this repository's Git rules. A
fresh clone may not include them: obtain the existing broker deployment files,
or provision a new CA/server certificate with SANs matching the hostnames/IPs
you will use, before starting. Do not overwrite the working CA just to run locally.

## 3. Configure MQTT accounts

If the existing accounts and passwords are known, reuse them and skip this step.
Otherwise, add/update accounts interactively; substitute your chosen usernames:

```sh
mosquitto_passwd comms/broker/certs/passwordfile laptop_cli
mosquitto_passwd comms/broker/certs/passwordfile ultra96
mosquitto_passwd comms/broker/certs/passwordfile phone
```

Each command prompts for a password. Updating an existing username changes its
password, so update that client's credentials too. Restart the broker afterward.

**Only if `passwordfile` does not exist**, create it with the first account:

```sh
mosquitto_passwd -c comms/broker/certs/passwordfile laptop_cli
```

Then add the remaining accounts without `-c`. The `-c` flag overwrites an existing
password file. The current broker has no topic ACL: authenticated accounts can
use all application topics.

## 4. Start the project broker

In terminal 1:

```sh
mosquitto -c "$PWD/comms/broker/mosquitto.conf" -v
```

Keep this terminal open. Stop the broker with **Ctrl-C**. Successful startup logs
show the listener on port 8883 (and 9001 with the existing full configuration).

Use the explicit project configuration above. `brew services start mosquitto`
uses Homebrew's configuration, which may not contain this project's TLS settings.
If a Homebrew service already occupies the port, inspect it with
`brew services list`; stop that service with `brew services stop mosquitto` before
starting the project instance.

## 5. Verify publish/subscribe locally

In terminal 2, substitute an existing MQTT username and password:

```sh
mosquitto_sub -h localhost -p 8883 \
  --cafile "$PWD/comms/broker/certs/ca.crt" \
  -u 'YOUR_USERNAME' -P 'YOUR_PASSWORD' \
  -t 'test/local-broker' -C 1 -v
```

In terminal 3, publish using valid credentials:

```sh
mosquitto_pub -h localhost -p 8883 \
  --cafile "$PWD/comms/broker/certs/ca.crt" \
  -u 'YOUR_USERNAME' -P 'YOUR_PASSWORD' \
  -t 'test/local-broker' -m 'broker works'
```

Terminal 2 should print `test/local-broker broker works` and exit. Passwords passed
with `-P` can appear in shell history/process arguments; use test credentials for
these manual checks.

## 6. Run the complete local test without hardware

Use the existing `comms/.venv` if available. For a new macOS environment:

```sh
python3 -m venv comms/.venv
comms/.venv/bin/python -m pip install -r comms/requirements.txt
```

Create or edit `comms/.env`, preserving any existing entries. Set these to the
accounts/passwords in Mosquitto's password file:

```dotenv
USER_LAPTOP_CLI=laptop_cli
PW_LAPTOP_CLI=replace_with_laptop_password
USER_ULTRA96_COMMS=ultra96
PW_ULTRA96_COMMS=replace_with_ultra96_password
```

In terminal 2, start the simulated Ultra96 consumer on the laptop:

```sh
export BROKER_HOST=localhost
export CA_CERTS_PATH="$PWD/comms/broker/certs/ca.crt"
comms/.venv/bin/python comms/ultra96/ultra96_comms.py
```

In terminal 3, start the dummy sender:

```sh
export BROKER_HOST=localhost
export CA_CERTS_PATH="$PWD/comms/broker/certs/ca.crt"
comms/.venv/bin/python comms/laptop/send_dummy_sensors.py --interval 2
```

Export the broker/CA overrides **before starting Python**: shared constants read
them at import time, before these scripts call `load_dotenv()`.

Expected flow:

```text
Dummy sender → local broker → simulated Ultra96 consumer
             ← local broker ← AI result
```

The sender generates 200 paired samples over one second, starting a capture every
two seconds, and prints incoming AI results. This consumer returns random
predictions; this verifies MQTT transport and collection, not DPU inference.
QoS 0 sensor delivery can lose packets. Dummy input does not trigger haptics.
Run this separately from the real BLE pipeline and other sensor publishers.

## 7. Connect the real Ultra96 or phone

For a direct network connection, use the laptop's reachable LAN hostname/IP as
the broker host. `localhost` on the Ultra96 or phone refers to that device itself.
The chosen hostname/IP must appear in the broker certificate SANs. Allow incoming
connections to Mosquitto through the macOS firewall and use a network that permits
device-to-device traffic.

- **Ultra96:** deploy the consumer and sibling `utilities` directory, plus the
  public `ca.crt`. Set `BROKER_HOST` before launching Python.
- **Reverse SSH tunnel:** if your existing tunnel forwards Ultra96's local port
  8883 to the laptop broker, use `BROKER_HOST=localhost` on Ultra96. The tunnel
  must be running; starting Mosquitto alone does not create it.
- **Unity phone:** configure the laptop's reachable address, port `8883`, and
  MQTT credentials. Ensure the app trusts the same CA. A replacement CA requires
  updating the app's bundled trust certificate too.

The two Ultra96 entry points currently have different settings:

| Entry point | Credential environment variables | CA certificate | Inference |
|---|---|---|---|
| `ultra96_comms.py` | `USER_ULTRA96_COMMS`, `PW_ULTRA96_COMMS` | `CA_CERTS_PATH` override | Random predictions, one-second windows |
| `ultra96_comms_dpu.py` | `USER_ULTRA96`, `PW_ULTRA96` | Hard-coded `/comms/ca.crt` | Local DPU server at `/tmp/pickleviz_dpu.sock` |

For DPU testing, provide those DPU credentials in the Ultra96 environment or
`.env`, install the CA at `/comms/ca.crt`, and start the DPU server before the
consumer. `CA_CERTS_PATH` does not override that script's hard-coded CA path.
Run only the intended consumer to avoid duplicate results.

## Troubleshooting

| Symptom | Check |
|---|---|
| Address already in use | `lsof -nP -iTCP:8883 -sTCP:LISTEN` and the equivalent for port 9001; identify the existing broker before stopping it. |
| Cannot load CA, server key, or password file | Absolute paths in `mosquitto.conf` and read permission for the user running Mosquitto. |
| Certificate verification fails | CA trust, certificate expiry, machine clock, and hostname/IP SAN match. |
| Not authorised / connection rejected | Username/password, matching `.env` variable names, and broker restart after password changes. |
| Connection refused | Broker process and port; on a remote device, ensure `localhost` is intentional. |
| Remote connection times out | Routing, firewall, network client isolation, or an inactive SSH tunnel. |
| No results | Consumer subscription/connection, sender logs, and matching broker host; DPU mode also needs its local inference server. |
| WebSocket listener fails | If only using current Python/Unity TCP clients, remove the optional 9001 listener block from your local config and retain the 8883 TLS listener. |

## References

- [Homebrew Mosquitto installation and service configuration](https://formulae.brew.sh/formula/mosquitto)
- Installed manuals: `man mosquitto.conf`, `man mosquitto_passwd`, `man mosquitto_sub`.
- Project implementation: `mosquitto.conf`, `../utilities/constants.py`,
  `../utilities/mqtt_client.py`, and the two Ultra96 entry points.
