import logging 
import sys
from pathlib import Path
from datetime import datetime


def get_logger(name: str, verbose: bool = False, log_dir: str = "logs") -> logging.Logger:
    """
    Creates a logger that writes DEBUG-level detail to a timestamped log file,
    and INFO-level (or DEBUG if verbose=True) to the console.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # capture everything; handlers filter what's shown

    if logger.handlers:
        # avoid duplicate handlers if get_logger() is called more than once
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%d-%m-%Y %H:%M:%S",
    )

    # Console handler 
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler: always DEBUG, regardless of -v 
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%d-%m-%Y_%H:%M:%S")
    log_path = Path(log_dir) / f"{name}_{timestamp}.log"

    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.info(f"Logging to {log_path} (console level: {'DEBUG' if verbose else 'INFO'})")
    return logger