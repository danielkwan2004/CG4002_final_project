# Manual MQTT/TLS broker setup

The final product uses Mosquitto with TCP/TLS on port 8883 and username/password
authentication. If you already have a working broker, reuse its certificates, configuration
and accounts; skip certificate generation.

Run commands from the directory containing `comms/`, using a macOS/Linux shell.

## 1. Install tools

On macOS:

```sh
brew install mosquitto openssl
export PATH="$(brew --prefix openssl)/bin:$(brew --prefix)/sbin:$PATH"
```

On Debian/Ubuntu:

```sh
sudo apt install mosquitto mosquitto-clients openssl
```

The commands below require OpenSSL with `req -addext` support (1.1.1 or later).
Run the project broker as your normal user. Check whether an existing broker
service already occupies port 8883 before starting another instance.

## 2. Create certificates for a fresh deployment

Use these commands only when `comms/broker/certs/` does not already exist.
The plain `mkdir` deliberately fails for an existing directory; do not continue
if it fails. Keep the same terminal open through the certificate/config steps.

```sh
mkdir -p comms/broker
mkdir -m 700 comms/broker/certs
export PICKLEVIZ_CERT_DIR="$PWD/comms/broker/certs"
```

Generate a private CA and broker key. A restrictive umask protects new files:

```sh
(
  umask 077
  openssl genrsa -out "$PICKLEVIZ_CERT_DIR/ca.key" 2048
  openssl req -x509 -new -sha256 -days 365 \
    -key "$PICKLEVIZ_CERT_DIR/ca.key" \
    -out "$PICKLEVIZ_CERT_DIR/ca.crt" \
    -subj "/CN=PickleViz development CA" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"
  openssl genrsa -out "$PICKLEVIZ_CERT_DIR/server.key" 2048
  openssl req -new -key "$PICKLEVIZ_CERT_DIR/server.key" \
    -out "$PICKLEVIZ_CERT_DIR/server.csr" -subj "/CN=PickleViz broker"
)
```

Create `comms/broker/certs/server.ext` with this content. **Use your broker laptop's Tailscale IP**.
Add`,DNS:your-hostname` if clients will connect by hostname. SAN entries must match
what clients enter as `BROKER_HOST`.

```ini
subjectAltName=DNS:localhost,IP:127.0.0.1,IP:YOUR_LAPTOP_TAILSCALE_IP
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
```

Sign and check the broker certificate:

```sh
openssl x509 -req -in "$PICKLEVIZ_CERT_DIR/server.csr" \
  -CA "$PICKLEVIZ_CERT_DIR/ca.crt" -CAkey "$PICKLEVIZ_CERT_DIR/ca.key" \
  -CAcreateserial -out "$PICKLEVIZ_CERT_DIR/server.crt" \
  -days 365 -sha256 -extfile "$PICKLEVIZ_CERT_DIR/server.ext"
openssl verify -CAfile "$PICKLEVIZ_CERT_DIR/ca.crt" "$PICKLEVIZ_CERT_DIR/server.crt"
openssl x509 -in "$PICKLEVIZ_CERT_DIR/server.crt" -noout -dates -ext subjectAltName
```

Verification should report `OK`. Clients need only the public `ca.crt`.
Keep CA/server private keys on the broker/signing machine. Replacing the CA
requires updating every client's trust certificate, including the phone app.

## 3. Create MQTT accounts

For a new password file, create the laptop account first, then add the others:

```sh
mosquitto_passwd -c comms/broker/certs/passwordfile laptop_cli
mosquitto_passwd comms/broker/certs/passwordfile ultra96
mosquitto_passwd comms/broker/certs/passwordfile phone
chmod 600 comms/broker/certs/passwordfile
```

Each command prompts for a password. Use `-c` only for a new file: it overwrites
existing accounts. For an existing deployment, reuse its account names/passwords
or update accounts without `-c`, then restart the broker.

Set the matching laptop/Ultra96 credentials in each machine's `comms/.env`.
The phone account is entered in the app. The final DPU consumer uses
`USER_ULTRA96`/`PW_ULTRA96`.

## 4. Enable topic permissions

Include the supplied [acl](acl) file at `comms/broker/acl`. Rules match MQTT **usernames**,
not client IDs. The defaults match the accounts created above and `.env.example`:

| Username | Publish | Subscribe / receive |
|---|---|---|
| `laptop_cli` | `fb/sensor/raw`; latency requests for laptop, Ultra96 and phone; `latency/laptop/resp` | Haptics, handedness, Ultra96 status; laptop latency requests/responses |
| `ultra96` | AI results, haptics, `sys/ultra96/status`; `latency/laptop/resp` | Sensor data, handedness; `latency/ultra96/req` |
| `phone` | Retained handedness; `latency/laptop/resp` | Sensor data, AI results, Ultra96 status; `latency/phone/req` |

Unlisted topics and users have no topic access. No wildcard grants are used.
Authentication still uses the existing password file. If you use different
usernames, update the corresponding `user` lines in `acl`; do not change working
client credentials just to match the examples. Accounts must be distinct for
these role restrictions to work.

The optional `ultra96_comms` simulator account is intentionally not granted
permissions by this final-product ACL. The unused demo sender also cannot receive
AI results using `laptop_cli`.  Status-read permissions allow optional monitoring; they do not make the current applications display Last Will messages automatically.

## 5. Write the broker configuration

Create `comms/broker/mosquitto.conf` with the following content. Replace every
`/absolute/path/to/comms/broker/certs` with the actual path printed by
`echo "$PICKLEVIZ_CERT_DIR"`. Also replace the ACL path with the absolute path
to `comms/broker/acl`. These are literal paths, not shell variables.

```conf
listener 8883
protocol mqtt
allow_anonymous false
cafile /absolute/path/to/comms/broker/certs/ca.crt
certfile /absolute/path/to/comms/broker/certs/server.crt
keyfile /absolute/path/to/comms/broker/certs/server.key
require_certificate false
password_file /absolute/path/to/comms/broker/certs/passwordfile
acl_file /absolute/path/to/comms/broker/acl
```

Clients validate the server certificate and authenticate with a password; they
do not supply client certificates. The ACL restricts each authenticated account
to its listed topics. If you move the deployment, update these paths. The broker
process must be able to read the ACL file.

## 6. Start and verify the broker

```sh
mosquitto -c "$PWD/comms/broker/mosquitto.conf" -v
```

If the project broker is already running, stop it with Ctrl-C in its terminal
before starting the updated configuration. Do not start a second listener on
the same port. Keep this terminal open; stop with Ctrl-C. Run as the owner of the generated
files so the broker can read the restricted key directory.

Stop the application clients for this manual check so diagnostic payloads are
not consumed as real sensor data. Use two additional terminals, both in the
directory containing `comms/`. Replace password placeholders with the passwords
for the named accounts. If your usernames differ, use their ACL equivalents.

Subscriber (an allowed sensor-data reader):

```sh
mosquitto_sub -h localhost -p 8883 \
  --cafile "$PWD/comms/broker/certs/ca.crt" \
  -u ultra96 -P 'YOUR_ULTRA96_PASSWORD' -t fb/sensor/raw -C 1 -v
```

Publisher (the only account allowed to produce sensor data):

```sh
mosquitto_pub -h localhost -p 8883 \
  --cafile "$PWD/comms/broker/certs/ca.crt" \
  -u laptop_cli -P 'YOUR_LAPTOP_PASSWORD' -t fb/sensor/raw \
  -m '{"acl_check":"broker works"}' -q 1
```

The subscriber should print `fb/sensor/raw {"acl_check":"broker works"}` and exit.
The payload is a broker diagnostic, not a valid application sensor packet.
Passwords passed on the command line can appear in shell history/process listings.

Now test a forbidden operation: the phone must not publish sensor measurements.
MQTT 5 exposes the broker's rejection explicitly for a QoS 1 publish:

```sh
mosquitto_pub -V mqttv5 -h localhost -p 8883 \
  --cafile "$PWD/comms/broker/certs/ca.crt" \
  -u phone -P 'YOUR_PHONE_PASSWORD' -t fb/sensor/raw \
  -m '{"acl_check":"must be denied"}' -q 1
```

Expect a not-authorised publish response and no delivery of that message to
sensor subscribers. Keep an allowed subscriber running if checking non-delivery.
For MQTT 3.1.1 clients, a local publish success or acknowledgement alone does not
prove broker authorisation; rejected messages may simply not be forwarded.
Likewise, a subscription acknowledgement alone is insufficient to test read
permissions: Mosquitto can accept a filter while suppressing unauthorised data.
The former `test/comms` topic is not allowed by this ACL.

The supplied ACL was also checked on an isolated TLS broker with MQTT 3.1.1 and
MQTT 5: allowed/denied publish routes, per-account read filtering, an authenticated
but unlisted account, retained handedness delivery, a blocked retained overwrite,
Ultra96 Last Will delivery and anonymous-connection rejection. These checks do
not require BLE hardware. They do not replace a live application check after
the production broker is restarted.

This verifies TLS, authentication and MQTT delivery without project demo scripts
or hardware. Continue with the [live system instructions](../README.md).
For the final deployment, keep Tailscale connected on the broker laptop and
Ultra96 in the same tailnet. Follow the
[Tailscale setup](../README.md#network-connection-using-tailscale). Allow TCP 8883
in the tailnet policy and laptop firewall. The `listener 8883` configuration
above accepts remote connections; do not replace it with a loopback-only listener.

Run the subscriber command on Ultra96, replacing `-h localhost` with
`-h YOUR_LAPTOP_TAILSCALE_IP` and `--cafile` with Ultra96's actual local CA path
(for example `/comms/ca.crt`). Keep the sensor publisher on the laptop using
`laptop_cli`; the Ultra96 account is intentionally not permitted to publish sensor
data. This verifies the Tailscale route, MQTT authentication and TLS trust.
No reverse SSH tunnel or public router port forwarding is needed.

## Troubleshooting

| Failure | Check |
|---|---|
| Command not found | Tool installation and bin/sbin directories on PATH |
| Address in use | Existing broker/service listening on 8883 |
| Cannot load config/key/password file | Absolute paths and permissions for the broker user |
| Certificate verification failed | CA trust, hostname/IP SAN, expiry and device clock |
| Connection rejected | Account/password, anonymous access disabled and correct credential variable names |
| Connected but data missing / publish denied | ACL username, exact topic and read/write permission; restart after enabling the ACL |
| Remote timeout | Both Tailscale devices connected, correct laptop Tailscale IP, tailnet access policy, laptop firewall and non-loopback broker listener |
