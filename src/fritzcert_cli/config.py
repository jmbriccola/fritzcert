"""
Configuration management for fritzcert
--------------------------------------
Reads and writes the YAML configuration file:
  /etc/fritzcert/config.yaml

Expected structure:
boxes:
  - name: boxname
    domain: sub.boxdomain.com
    key_type: 2048
    dns_provider:
      plugin: dns_gd
      credentials:
        GD_Key: "abc"
        GD_Secret: "def"
    fritzbox:
      url: https://sub.boxdomain.com
      username: letsencrypt
      password: "secret"
"""

from __future__ import annotations
import os
import yaml
import shutil
import pathlib
from typing import Any, Dict, List
import datetime as _dt

CONFIG_PATH = pathlib.Path("/etc/fritzcert/config.yaml")
CONFIG_DIR = CONFIG_PATH.parent
BACKUP_DIR = CONFIG_DIR / "backups"

DEFAULT_KEY_TYPE = "2048"


class ConfigError(RuntimeError):
    """Generic configuration error."""


def ensure_dirs() -> None:
    """Ensure the configuration and backup directories exist."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        raise ConfigError(
            "Insufficient permissions to create /etc/fritzcert. "
            "Retry with: sudo fritzcert init"
        ) from e


def _backup_config() -> None:
    """Create a backup copy of the configuration file before modifying it."""
    if CONFIG_PATH.exists():
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = BACKUP_DIR / f"config-{ts}.yaml"
        shutil.copy2(CONFIG_PATH, backup_path)


def _load_yaml() -> dict:
    """Load the YAML configuration file, or return an empty dict if missing."""
    if not CONFIG_PATH.exists():
        return {"boxes": []}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "boxes" not in data:
        data["boxes"] = []
    return data


def _save_yaml(data: dict) -> None:
    """Atomically save the YAML configuration file."""
    ensure_dirs()
    tmp_path = CONFIG_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    _backup_config()
    tmp_path.replace(CONFIG_PATH)


# ------------------------------------------------------------
# Public API
# ------------------------------------------------------------

def list_boxes() -> List[Dict[str, Any]]:
    """Return the list of all configured boxes."""
    cfg = _load_yaml()
    return cfg.get("boxes", [])


def get_box(name: str) -> Dict[str, Any]:
    """Return the configuration for a specific box by name."""
    cfg = _load_yaml()
    for box in cfg.get("boxes", []):
        if box["name"] == name:
            return box
    raise ConfigError(f"Box '{name}' not found.")


def add_or_update_box(
    name: str,
    domain: str,
    dns_plugin: str,
    key_type: str = DEFAULT_KEY_TYPE,
    dns_credentials: Dict[str, str] | None = None,
    fritzbox: Dict[str, str] | None = None,
) -> None:
    """Add or update a box configuration."""
    cfg = _load_yaml()
    boxes = cfg.setdefault("boxes", [])

    # Remove if an entry with the same name already exists
    boxes = [b for b in boxes if b.get("name") != name]

    new_box = {
        "name": name,
        "domain": domain,
        "key_type": key_type,
        "dns_provider": {
            "plugin": dns_plugin,
            "credentials": dns_credentials or {},
        },
        "fritzbox": fritzbox or {},
    }

    boxes.append(new_box)
    cfg["boxes"] = boxes
    _save_yaml(cfg)


def remove_box(name: str) -> None:
    """Remove a box configuration by name."""
    cfg = _load_yaml()
    boxes = [b for b in cfg.get("boxes", []) if b.get("name") != name]
    if len(boxes) == len(cfg.get("boxes", [])):
        raise ConfigError(f"No box found with name '{name}'.")
    cfg["boxes"] = boxes
    _save_yaml(cfg)


def update_box(name: str, updates: Dict[str, Any]) -> None:
    """Update existing fields in a box configuration."""
    cfg = _load_yaml()
    found = False
    for box in cfg.get("boxes", []):
        if box["name"] == name:
            found = True
            # Shallow merge
            for k, v in updates.items():
                if k == "dns_provider" and isinstance(v, dict):
                    box["dns_provider"].update(v)
                elif k == "fritzbox" and isinstance(v, dict):
                    box["fritzbox"].update(v)
                else:
                    box[k] = v
            break
    if not found:
        raise ConfigError(f"Box '{name}' not found.")
    _save_yaml(cfg)


def validate_box(box: Dict[str, Any]) -> None:
    """Validate that a box configuration contains all required fields."""
    required_fields = ["name", "domain", "dns_provider", "fritzbox"]
    for f in required_fields:
        if f not in box or not box[f]:
            raise ConfigError(f"Missing field: {f}")
    if "plugin" not in box["dns_provider"]:
        raise ConfigError("Missing dns_provider.plugin.")
    if "url" not in box["fritzbox"]:
        raise ConfigError("Missing fritzbox.url.")


def set_account(ca: str, email: str) -> None:
    """Set the CA (letsencrypt|zerossl) and email in /etc/fritzcert/config.yaml."""
    if ca not in ("letsencrypt", "zerossl"):
        raise ConfigError("Invalid CA value. Use: letsencrypt or zerossl.")
    if not email or "@" not in email:
        raise ConfigError("Invalid email address.")
    cfg = _load_yaml()
    cfg.setdefault("account", {})
    cfg["account"]["ca"] = ca
    cfg["account"]["email"] = email
    _save_yaml(cfg)
