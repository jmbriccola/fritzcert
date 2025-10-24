"""
utils.py – shared functions and constants
"""

from __future__ import annotations
import os
import pathlib
import datetime

# Global paths
CONF_DIR = pathlib.Path("/etc/fritzcert")
CONF_FILE = CONF_DIR / "config.yaml"
STATE_DIR = pathlib.Path("/var/lib/fritzcert")
LOG_DIR = pathlib.Path("/var/log/fritzcert")

for d in (CONF_DIR, STATE_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "fritzcert.log"


def log(message: str) -> None:
    """Write a message to stdout and to the global log file."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def chmod_safe(path: pathlib.Path, mode: int = 0o600) -> None:
    """Set file permissions safely if the file exists."""
    try:
        if path.exists():
            os.chmod(path, mode)
    except Exception:
        pass


def check_root() -> None:
    """Check if the command is being executed with sufficient privileges."""
    if os.geteuid() != 0:
        print("Warning: some operations require root privileges (sudo).")


def confirm(prompt: str) -> bool:
    """Ask the user for confirmation (yes/no)."""
    resp = input(f"{prompt} [y/N]: ").strip().lower()
    return resp in ("y", "yes")
