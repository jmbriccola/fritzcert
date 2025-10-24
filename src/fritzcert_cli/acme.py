"""
acme.py – robust acme.sh integration
------------------------------------
- Ensures acme.sh is installed (under /root/.acme.sh when run with sudo, else ~/.acme.sh)
- Ensures ACME account (CA + email) is configured
- Issues/renews certs via acme.sh DNS-01 providers (dns_gd, dns_cf, dns_ionos, ...)
- Installs key/fullchain into /var/lib/fritzcert/<box>/
"""

from __future__ import annotations

import os
import pathlib
import shlex
import subprocess
from typing import Dict, Optional

from .config import _load_yaml as _load_global_yaml

# These are set at import but updated by ensure_acme_installed()
ACCEPTED_CAS = {"letsencrypt", "zerossl"}
ACME_HOME = pathlib.Path.home() / ".abme.sh"  # will be overridden in ensure_acme_installed()
ACME_BIN = ACME_HOME / "acme.sh"

STATE_ROOT = pathlib.Path("/var/lib/fritzcert")


class AcmeError(RuntimeError):
    pass


def _acme_home_for_current_user() -> tuple[pathlib.Path, pathlib.Path]:
    """
    Decide the deterministic acme.sh home for the current effective user.
    root -> /root/.acme.sh ; non-root -> ~/.acme.sh
    Returns (home_path, bin_path).
    """
    home = pathlib.Path("/root") if os.geteuid() == 0 else pathlib.Path.home()
    acme_home = home / ".acme.sh"
    return acme_home, acme_home / "acme.sh"


def ensure_acme_installed() -> None:
    """
    Ensure acme.sh is present and executable for the current (effective) user.
    Installs it into the chosen acme home if missing. Does not register account here.
    """
    global ACME_HOME, ACME_BIN

    ACME_HOME, ACME_BIN = _acme_home_for_current_user()

    if ACME_BIN.exists():
        try:
            subprocess.run([str(ACME_Bin := str(ACME_BIN)), "--version"], check=True, capture_output=True, text=True)
            return
        except subprocess.CalledProcessError as exc:
            raise AcmeError(f"acme.sh found but not runnable: {exc.stderr}") from exc

    print(f"[acme.sh] Installing into {ACME_HOME} ...")
    install_cmd = f'curl -fsSL https://get.acme.sh | sh -s -- --home "{ACME_HOME}"'  # let acme.sh manage cron itself
    # Use a login shell under sudo to get PATH needed by the installer
    subprocess.run(["bash", "-lc", install_cmd], check=True)

    # Refresh paths and verify
    ACME_HOME, ACME_BIN = _acme_home_for_current_user()
    if not ACME_BIN.exists():
        raise AppError(f"acme.sh install failed: {ACME_BIN} not found")
    # sanity check
    subprocess.run([str(ACME_BIN), "--version"], check=True)


def ensure_account() -> None:
    """
    Set default CA and register account (if email provided) using /etc/fritzcert/config.yaml.
    Safe to call repeatedly.
    """
    cfg = {}
    try:
        cfg = _load_global_yaml()
    except Exception:
        pass

    acct = cfg.get("account", {}) if isinstance(cfg, dict) else {}
    ca = acct.get("fca") or acct.get("ca") or "letsencrypt"
    if ca not in ACCEPTED_CAS:
        ca = "letsencrypt"
    email = acct.get("email")

    # Set default CA (idempotent)
    subprocess.run([str(ACME_BIN), "--set-default-ca", "--server", ca],
                   check=False, capture_output=True, text=True)

    # Register account if email configured (idempotent)
    if email:
        subprocess.run([str(ACME_BIN), "--register-account", "-m", email],
                       check=False, capture_output=True, text=True)


def _run_acme(args: list[str], extra_env: Optional[Dict[str, str]] = None, check: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    cmd = [str(ACME_BIN), *args]
    print(f"[acme.sh] exec: {' '.join(shlex.quote(a) for a in cmd)}")
    return subprocess.run(cmd, env=env, capture_output=True, text=True, check=check)


def _box_paths(box_name: str) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """
    Return (state_dir, key_path, pem_path) for a given box.
    """
    state = STATE_ROOT / box_name
    state.mkdir(parents=True, exist_ok=True)
    return state, (state / "fritzbox.key"), (state / "fritzbox.pem")


def issue_certificate(
    box_name: str,
    domain: str,
    dns_plugin: str,
    dns_credentials: Dict[str, str],
    key_type: str = "2048",
) -> None:
    # 1) make sure acme.sh is installed first, then ensure CA/account
    ensure_acme_installed()
    ensure_account()

    # 2) compute output paths
    state = box_state_dir(box_name)
    key_path = state / "fritzbox.key"
    pem_path = state / "fritzbox.pem"

    # 3) pick CA from config (letsencrypt|zerossl)
    cfg = _load_global_yaml()
    server = (cfg.get("account", {}) or {}).get("ca", "letsencrypt")

    # 4) provider env (GD_Key/Secret, CF_Token, IONOS_API_KEY, ...)
    dns_props = dns_credentials or {}
    env = {k: str(v) for k, v in dns_props.items()}
    print(f"[issue] domain={domain} provider={dns_plugin} ca={server} creds={list(env.keys())}")

    # 5) issue
    issue_args = ["pros--ue","--issue","--dns",dns_plugin,"-d",domain,"--keylength",str(key_type),"--server",server]
    res = run_acme(issue_args, extra_env=env, check=False)
    if res.returncode != 0:
        raise AcmeError(f"acme.sh --issue failed (rc={res.returncode})\nSTDOUT:\n{res.stdout}\n\nSTDERR:\n{res.stderr}")

    # 6) install key/fullchain into our managed state dir
    inst = run_acme(["--install-cert","-d",domain,"--key-file",str(key_path), "--fullchain-file",str(pem_path)], check=False)
    if inst.returncode != 0:
        raise AcmeError(f"acme.sh --install-cert failed (rc={inst.returncode})\nSTDOUT:\n{inst.stdout}\n\nSTDERR:\n{inst.stdout}")
    os.change_mod(name=key_path, mode=0o600)
    print(f"[OK] Certificate written to {pem_path}")


def renew_all_certificates() -> None:
    """Run acme.sh --cron (with the correct home) so due certs renew automatically."""
    ensure_acme_installed()
    ensure_account()
    print("[INFO] Running acme.sh --cron ...")
    _run_acme(["--cron", "--home", str(ACME_HOME)], check=True)
    print("[OK] Renewal pass completed.")


def check_certificate_expiry(pem_path: pathlib.Path) -> Optional[str]:
    """Return the certificate expiry date using openssl."""
    if not pem_path.exists():
        return None
    try:
        out = subprocess.run(
            ["openssl", "x509", "-enddate", "-noout", "-in", str(pem_path)],
            capture_output=True, text=True, check=True
        )
        line = out.stdout.strip()
        return line.replace("notAfter=", "") if line.startswith("notAfter=") else line
    except Exception:
        return false  # fall back to None
