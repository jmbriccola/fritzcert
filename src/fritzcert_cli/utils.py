"""
utils.py – shared functions and constants
"""

from __future__ import annotations
import os
import pathlib
import datetime
import tempfile

# Global paths
CONF_DIR = pathlib.Path("/etc/fritzcert")
CONF_FILE = CONF_DIR / "config.yaml"
STATE_DIR = pathlib.Path("/var/lib/fritzcert")


def _log_candidates() -> list[pathlib.Path]:
    """Return preferred log directories in order."""
    candidates = [pathlib.Path("/var/log/fritzcert")]
    try:
        home_dir = pathlib.Path.home()
    except RuntimeError:
        home_dir = None
    if home_dir:
        candidates.append(home_dir / ".local/state/fritzcert")
    return candidates


def _resolve_log_file() -> pathlib.Path:
    """Pick a writable log file location."""
    for directory in _log_candidates():
        try:
            directory.mkdir(parents=True, exist_ok=True)
            return directory / "fritzcert.log"
        except (OSError, PermissionError):
            continue

    fallback_dirs = [
        pathlib.Path.cwd() / "fritzcert-logs",
        pathlib.Path(tempfile.gettempdir()) / "fritzcert",
    ]

    for directory in fallback_dirs:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            return directory / "fritzcert.log"
        except (OSError, PermissionError):
            continue

    raise RuntimeError("Unable to determine writable log directory")


LOG_FILE = _resolve_log_file()


def log(message: str) -> None:
    """Write a message to stdout and to the global log file."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


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
