"""Compatibility entry point; capture implementation lives with the firmware."""

from CG4002_hardware.diagnostics.wifi_receiver import main


if __name__ == "__main__":
    raise SystemExit(main())
