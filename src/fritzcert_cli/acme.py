"""
acme.py module
--------------
Handles Let's Encrypt operations via acme.sh.
Supports any DNS provider (dns_gd, dns_cf, dns_ionos, etc.).
Reads credentials from the YAML configuration file.

Each Fritz!Box has its own directory in /var/lib/fritzcert/<name>/
"""

from __future__ import annotations
import os
import subprocess
import pathlib
import shlex
from .config import _load_yaml as _load_global_yaml
from typing import Dict, Optional

ACME_HOME = pathlib.Path.home() / ".acme.sh"
ACME_BIN = ACME_HOME / "acme.sh"

STATE_BASE = pathlib.Path("/var/lib/fritzcert")

class AcmeError(RuntimeError):
    pass


def ensure_account():
    """
    Sets the default CA and registers the account if an email is configured
    in /etc/fritzcert/config.yaml. Does not fail if already registered.
    """
    try:
        cfg = _load_global_yaml()
    except Exception:
        cfg = {}
    acct = cfg.get("account", {}) if isinstance(cfg, dict) else {}
    ca = acct.get("ca", "letsencrypt")
    email = acct.get("email")

    # Set CA (idempotent)
    subprocess.run([str(ACME_BIN), "--set-default-ca", "--server", ca],
                   check=False, capture_output=True, text=True)

    # Register account if email is present
    if email:
        subprocess.run([str(ACME_BIN), "--register-account", "-m", email],
                       check=False, capture_output=True, text=True)


def ensure_acme_installed() -> None:
    """
    Installs acme.sh if missing. If already present, it will not upgrade
    (to avoid sudo/policy errors).
    """
    if ACME_BIN.exists():
        # Verify that it is executable
        try:
            subprocess.run([str(ACME_BIN), "--version"], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise AcmeError(f"acme.sh is present but not executable: {e.stderr}") from e
        return

    print("Installing acme.sh ...")
    cmd = "curl https://get.acme.sh | sh"
    # Note: with sudo this installs under /root/.acme.sh
    subprocess.run(["bash", "-lc", cmd], check=True)
    # Post-install verification
    if not ACME_BIN.exists():
        raise AcmeError(f"acme.sh installation failed: binary not found at {ACME_BIN}")


def run_acme(args: list[str], extra_env: Optional[Dict[str, str]] = None, check: bool = True):
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    cmd = [str(ACME_BIN)] + args
    print(f"Running: {' '.join(shlex.quote(a) for a in cmd)}")
    return subprocess.run(cmd, env=env, capture_output=True, text=True, check=check)

def box_state_dir(box_name: str) -> pathlib.Path:
    """Return the directory where certificates and keys are stored for a given box."""
    path = STATE_BASE / box_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def issue_certificate(box_name: str, domain: str, dns_plugin: str, dns_credentials: Dict[str, str], key_type: str = "2048") -> None:
    """Issues or renews a certificate for a box using the selected DNS provider."""
    ensure_account()
    ensure_acme_installed()
    box_dir = box_state_dir(box_name)
    key_file = box_dir / "fritzbox.key"
    pem_file = box_dir / "fritzbox.pem"

    # Environment for the provider (e.g., GD_Key, CF_Token, etc.)
    env = {k: str(v) for k, v in dns_credentials.items() if v}
    # Info: only variable names, never values
    print(f"Issuing certificate for {domain} (plugin={dns_plugin}, credentials={list(env.keys())})")
    
     # Read preferred CA (letsencrypt or zerossl) from config
    server = _load_global_yaml().get("account", {}).get("ca", "letsencrypt")

    # --issue    
    args = ["--issue", "--dns", dns_plugin, "-d", domain, "--keylength", key_type, "--server", server],
    res = run_acme(args, extra_env=env, check=False)
    if res.returncode != 0:
        raise AcmeError(
            f"acme.sh --issue error (rc={res.returncode})\n"
            f"STDOUT:\n{res.stdout}\n\nSTDERR:\n{res.stderr}"
        )

    # --install-cert
    inst = run_acme(["--install-cert", "-d", domain, "--key-file", str(key_file), "--fullchain-file", str(pem_file)], check=False)
    if inst.returncode != 0:
        raise AcmeError(
            f"acme.sh --install-cert error (rc={inst.returncode})\n"
            f"STDOUT:\n{inst.stdout}\n\nSTDERR:\n{inst.stderr}"
        )

    os.chmod(key_file, 0o600)
    print(f"Certificate saved at {pem_file}")

def renew_all_certificates() -> None:
    """
    Performs automatic renewal of all certificates managed by acme.sh.
    acme.sh itself checks which ones are due for renewal.
    """
    ensure_acme_installed()
    ensure_account()
    print("Renewing existing certificates...")
    run_acme(["--cron", "--home", str(ACME_HOME)])
    print("Renewal completed.")


def check_certificate_expiry(pem_path: pathlib.Path) -> Optional[str]:
    """Return the certificate expiry date using openssl."""
    if not pem_path.exists():
        return None
    try:
        result = subprocess.run(
            ["openssl", "x509", "-enddate", "-noout", "-in", str(pem_path)],
            capture_output=True, text=True, check=True
        )
        line = result.stdout.strip()
        if line.startswith("notAfter="):
            return line.replace("notAfter=", "")
        return line
    except Exception:
        return None


def show_status(box_name: str) -> None:
    """Display information about the current certificate of a box."""
    pem = STATE_BASE / box_name / "fritzbox.pem"
    key = STATE_BASE / box_name / "fritzbox.key"
    if not pem.exists():
        print(f"[{box_name}] No certificate found.")
        return
    expiry = check_certificate_expiry(pem)
    print(f"[{box_name}] Certificate: {pem}")
    print(f"  Key: {key}")
    print(f"  Expiry: {expiry or 'unknown'}")
