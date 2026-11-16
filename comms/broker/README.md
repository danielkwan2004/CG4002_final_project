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

## 4. Write the broker configuration

Create `comms/broker/mosquitto.conf` with the following content. Replace every
`/absolute/path/to/comms/broker/certs` with the actual path printed by
`echo "$PICKLEVIZ_CERT_DIR"`. These are literal absolute paths, not shell variables.

```conf
listener 8883
protocol mqtt
allow_anonymous false
cafile /absolute/path/to/comms/broker/certs/ca.crt
certfile /absolute/path/to/comms/broker/certs/server.crt
keyfile /absolute/path/to/comms/broker/certs/server.key
require_certificate false
password_file /absolute/path/to/comms/broker/certs/passwordfile
```

Clients validate the server certificate and authenticate with a password; they
do not supply client certificates. This configuration allows authenticated
accounts to use all application topics. If you move the deployment, update these paths.

## 5. Start and verify the broker

```sh
mosquitto -c "$PWD/comms/broker/mosquitto.conf" -v
```

Keep this terminal open; stop with Ctrl-C. Run as the owner of the generated
files so the broker can read the restricted key directory.

Use two additional terminals, both in the directory containing `comms/`.
Replace the credential placeholders with an account created above.

Subscriber:

```sh
mosquitto_sub -h localhost -p 8883 \
  --cafile "$PWD/comms/broker/certs/ca.crt" \
  -u YOUR_USERNAME -P YOUR_PASSWORD -t test/comms -C 1 -v
```

Publisher:

```sh
mosquitto_pub -h localhost -p 8883 \
  --cafile "$PWD/comms/broker/certs/ca.crt" \
  -u YOUR_USERNAME -P YOUR_PASSWORD -t test/comms -m 'broker works'
```

The subscriber should print `test/comms broker works` and exit. Quote passwords
containing shell-special characters. Command-line passwords can appear in shell
history/process listings; use temporary test credentials for this check.

This verifies TLS, authentication and MQTT delivery without project demo scripts
or hardware. Continue with the [live system instructions](../README.md).
For the final deployment, keep Tailscale connected on the broker laptop and
Ultra96 in the same tailnet. Follow the
[Tailscale setup](../README.md#network-connection-using-tailscale). Allow TCP 8883
in the tailnet policy and laptop firewall. The `listener 8883` configuration
above accepts remote connections; do not replace it with a loopback-only listener.

Repeat the MQTT check from Ultra96, replacing `-h localhost` with
`-h YOUR_LAPTOP_TAILSCALE_IP` and `--cafile` with Ultra96's actual local CA path
(for example `/comms/ca.crt`). Use the `ultra96` account and its configured
password. This verifies the Tailscale route, MQTT authentication and TLS trust.
No reverse SSH tunnel or public router port forwarding is needed.

## Troubleshooting

| Failure | Check |
|---|---|
| Command not found | Tool installation and bin/sbin directories on PATH |
| Address in use | Existing broker/service listening on 8883 |
| Cannot load config/key/password file | Absolute paths and permissions for the broker user |
| Certificate verification failed | CA trust, hostname/IP SAN, expiry and device clock |
| Not authorised | Account/password and correct credential variable names |
| Remote timeout | Both Tailscale devices connected, correct laptop Tailscale IP, tailnet access policy, laptop firewall and non-loopback broker listener |
