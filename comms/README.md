# Communications layout

- `utilities/`: shared packet constants, logging and MQTT wrapper.
- `laptop/`: BLE relay, synchroniser, file receiver and simulation scripts.
- `ultra96/`: AI-result and haptic service.
- `firebeetle/`: Arduino sketches, each kept inside its matching sketch directory.
- `unity-phone/`: Unity visualiser.
- `broker/`: broker configuration and certificates.

Run from the repository root (with the communications dependencies installed):

```sh
python comms/laptop/run_pipeline.py
python comms/laptop/run_pipeline.py -k
python comms/laptop/ble_file_transfer.py
python comms/ultra96/ultra96_comms.py
```

Direct execution from inside the laptop/Ultra96 directories also works.
The small `_bootstrap.py` modules expose the sibling utilities package.
Logs are stored under `comms/logs/`, independent of the working directory:
Ultra96 writes directly to `comms/logs/`. The laptop and simulators use
`laptop/`, `sim_phone/`, and `sim_ultra96/` subdirectories respectively.
Direct calls to `get_logger()` without a directory override also use
`comms/logs/` itself. Directories are created automatically.
Existing logs in older locations are not moved or deleted. Full DEBUG detail
is always saved to files; `-v` controls whether it also appears in the terminal.

For this logging update on Ultra96, copy `utilities/logger_setup.py` and
`ultra96/ultra96_comms.py`, preserving their sibling directory layout.
For example, a deployment at `/comms/` writes Ultra96 logs to
`/comms/logs/`. The account running Python needs write access there.

For Ultra96 deployment, copy both `ultra96/` and `utilities/`, retaining
their sibling layout. Keep credentials in the existing environment or `.env`.
Set machine-specific broker and CA paths as exported environment variables:

```sh
export BROKER_HOST=localhost
export CA_CERTS_PATH=/absolute/path/to/ca.crt
python comms/ultra96/ultra96_comms.py
```

These two overrides must be set before starting Python. Their defaults are
the laptop hostname and `comms/broker/certs/ca.crt`, resolved from the shared
module location rather than the current working directory. These must be set 
each time you access the Ultra96. Do not copy private broker keys to Ultra96; 
only its trusted CA certificate is needed.

Alternatively, change these manually in the `constants.py` file:
```sh
BROKER_HOST = "localhost"
CA_CERTS_PATH = "absolute/path/to/ca.crt"
```
