"""
utils.py – funzioni e costanti condivise
"""

from __future__ import annotations
import os
import pathlib
import datetime

# Percorsi globali
CONF_DIR = pathlib.Path("/etc/fritzcert")
CONF_FILE = CONF_DIR / "config.yaml"
STATE_DIR = pathlib.Path("/var/lib/fritzcert")
LOG_DIR = pathlib.Path("/var/log/fritzcert")

for d in (CONF_DIR, STATE_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "fritzcert.log"


def log(message: str) -> None:
    """Scrive un messaggio su stdout e nel log file globale."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def chmod_safe(path: pathlib.Path, mode: int = 0o600) -> None:
    """Imposta i permessi se il file esiste."""
    try:
        if path.exists():
            os.chmod(path, mode)
    except Exception:
        pass


def check_root() -> None:
    """Verifica che il comando sia eseguito con privilegi adeguati."""
    if os.geteuid() != 0:
        print("⚠️  Attenzione: alcune operazioni richiedono privilegi di root (sudo).")


def confirm(prompt: str) -> bool:
    """Chiede conferma all'utente (sì/no)."""
    resp = input(f"{prompt} [y/N]: ").strip().lower()
    return resp in ("y", "yes")
