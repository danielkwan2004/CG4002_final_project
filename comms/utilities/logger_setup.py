# Keep detailed packet evidence on disk while the default terminal shows INFO.
# Formatting happens on a logging thread so callbacks do not wait on file I/O.
import atexit
import json
import logging
import sys
import queue
from .constants import packet_type_name
from datetime import datetime
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path


DEVICE_COLORS = {
    "LAPTOP": "\033[94m",   # blue
    "FOREARM": "\033[92m",  # green
    "PADDLE": "\033[93m",   # yellow
    "ULTRA96": "\033[95m",  # magenta
    "PHONE": "\033[96m",    # cyan
}
RESET = "\033[0m"
DEFAULT_LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


class DeviceFormatter(logging.Formatter):
    """Adds a stable device column; colour is used only on the terminal."""

    def __init__(self, *args, colour=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.colour = colour

    def format(self, record):
        message = super().format(record)
        # Explicit source metadata wins; never infer a device from payload text.
        device = getattr(record, "device", record.name).upper()
        label = f"[{device:^7}]"
        if self.colour and sys.stdout.isatty():
            label = f"{DEVICE_COLORS.get(device, '')}{label}{RESET}"
        return f"{label} {message}"


def get_logger(name: str, verbose: bool = False, log_dir: str | Path = DEFAULT_LOG_DIR) -> logging.Logger:
    """
    Creates a logger that writes DEBUG-level detail to a timestamped log file,
    and INFO-level (or DEBUG if verbose=True) to the console.
    The default directory is comms/logs, independent of the working directory.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # capture everything; handlers filter what's shown

    if logger.handlers:
        # avoid duplicate handlers if get_logger() is called more than once
        return logger

    formatter = DeviceFormatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
        datefmt="%d-%m-%Y %H:%M:%S",
    )
    console_formatter = DeviceFormatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
        datefmt="%d-%m-%Y %H:%M:%S",
        colour=True,
    )

    # Console handler 
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(console_formatter)

    # File handler: always DEBUG, regardless of -v 
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%d-%m-%Y_%H:%M:%S")
    log_path = Path(log_dir) / f"{name}_{timestamp}.log"

    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    # BLE and MQTT callbacks must not wait for disk/terminal I/O per sample.
    # Keep every decoded packet in the file; formatting/output run on one worker.
    records = queue.SimpleQueue()
    logger.addHandler(QueueHandler(records))
    logger.propagate = False
    listener = QueueListener(records, console_handler, file_handler, respect_handler_level=True)
    listener.start()
    atexit.register(listener.stop)
    logger._packet_log_listener = listener

    logger.info(f"Logging to {log_path} (console level: {'DEBUG' if verbose else 'INFO'})")
    return logger


# The readable packet type is a log-only representation. Publishers continue
# sending numeric type fields, and binary BLE decoding remains separate.
def format_packet_for_log(payload):
    """Render a log-only copy with a readable type; leave wire data untouched."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode(errors="replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return payload
    if isinstance(payload, dict):
        payload = dict(payload)
        if "type" in payload:
            payload["type"] = packet_type_name(payload["type"])
    return json.dumps(payload)
