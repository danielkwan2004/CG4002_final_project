"""Allow direct scripts to find shared communication utilities."""
import sys
from pathlib import Path

# Resolve from this file, not the shell working directory, so direct invocation
# still finds the sibling utilities package on either machine.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
