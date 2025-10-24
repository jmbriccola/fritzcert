"""
acme.py – robust acme.sh integration
------------------------------------
- Ensures acme.sh is installed (under /root/.acme.sh when run with sudo, else ~/.acme.sh)
- Ensures ACME account (CA + email) is configured
- Issues/renews certs via acme.sh DNS-01 providers (dns_gd, dns_cf, dns_ionos, ...)
- Installs key/fullchain into /var/lib/fritzcert/<box>/
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import shlex
import subprocess
import tarfile
import tempfile
import urllib.request
from typing import Dict, Optional

from .config import _load_yaml as _load_global_yaml

ACCEPTED_CAS = {"letsencrypt", "zerossl"}

# Initialized at import, overridden by ensure_acme_installed()
ACME_HOME = pathlib.Path.home() / ".acme.sh"
ACME_BIN = ACME_HOME / "acme.sh"

STATE_ROOT = pathlib.Path("/var/lib/fritzcert")

ACME_VERSION = "3.0.6"
ACME_ARCHIVE_URL = f"https://github.com/acmesh-official/acme.sh/archive/refs/tags/{ACME_VERSION}.tar.gz"
ACME_ARCHIVE_SHA256 = "4a8e44c27e2a8f01a978e8d15add8e9908b83f9b1555670e49a9b769421f5fa6"


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


def _download_archive(dest: pathlib.Path) -> None:
    """Download the pinned acme.sh archive and verify its SHA256 checksum."""
    print(f"[acme.sh] Downloading {ACME_ARCHIVE_URL} ...")
    hasher = hashlib.sha256()
    try:
        with urllib.request.urlopen(ACME_ARCHIVE_URL, timeout=60) as resp, open(dest, "wb") as fh:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                fh.write(chunk)
                hasher.update(chunk)
    except Exception as exc:
        raise AcmeError(f"Failed to download acme.sh archive: {exc}") from exc

    digest = hasher.hexdigest()
    if digest != ACME_ARCHIVE_SHA256:
        raise AcmeError(
            "SHA256 mismatch downloading acme.sh archive. "
            f"Expected {ACME_ARCHIVE_SHA256}, got {digest}."
        )


def _safe_extract_tar(archive_path: pathlib.Path, destination: pathlib.Path) -> pathlib.Path:
    """Extract tar archive ensuring no path traversal, return extracted root directory."""
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            dest_resolved = destination.resolve()
            members = tar.getmembers()
            for member in members:
                member_path = dest_resolved / member.name
                if not member_path.resolve().is_relative_to(dest_resolved):
                    raise AcmeError(f"Unsafe path detected in archive: {member.name}")
            tar.extractall(destination)
    except AcmeError:
        raise
    except Exception as exc:
        raise AcmeError(f"Failed to extract acme.sh archive: {exc}") from exc

    candidates = [p for p in destination.iterdir() if p.is_dir() and p.name.startswith("acme.sh-")]
    if not candidates:
        raise AcmeError("Unexpected archive layout while installing acme.sh.")
    return candidates[0]


def _install_acme_sh(acme_home: pathlib.Path, acme_bin: pathlib.Path) -> None:
    """Download, verify, and install acme.sh into acme_home."""
    with tempfile.TemporaryDirectory(prefix="fritzcert_acme_") as tmp:
        tmpdir = pathlib.Path(tmp)
        archive_path = tmpdir / "acme.sh.tar.gz"
        _download_archive(archive_path)
        extract_root = tmpdir / "src"
        extract_root.mkdir(parents=True, exist_ok=True)
        source_dir = _safe_extract_tar(archive_path, extract_root)

        installer = source_dir / "acme.sh"
        if not installer.exists():
            raise AcmeError("Installer script acme.sh not found in extracted archive.")

        acme_home.mkdir(parents=True, exist_ok=True)

        cmd = [
            "bash",
            str(installer),
            "--install",
            "--home",
            str(acme_home),
            "--nocron",
            "--no-profile",
            "--force",
        ]
        env = os.environ.copy()
        env.setdefault("AUTOUPGRADE", "0")
        print(f"[acme.sh] Installing into {acme_home} ...")
        try:
            subprocess.run(
                cmd,
                check=True,
                env=env,
                capture_output=True,
                text=True,
                cwd=str(source_dir),
            )
        except subprocess.CalledProcessError as exc:
            raise AcmeError(
                f"acme.sh installation failed ({exc.returncode}): {exc.stderr}"
            ) from exc

    if not acme_bin.exists():
        raise AcmeError(f"acme.sh install failed: {acme_bin} not found")


def ensure_acme_installed() -> None:
    """
    Ensure acme.sh is present and executable for the current (effective) user.
    """
    global ACME_HOME, ACME_BIN

    ACME_HOME, ACME_BIN = _acme_home_for_current_user()

    if ACME_BIN.exists():
        try:
            subprocess.run([str(ACME_BIN), "--version"], check=True, capture_output=True, text=True)
            return
        except subprocess.CalledProcessError as exc:
            raise AcmeError(f"acme.sh found but not runnable: {exc.stderr}") from exc

    _install_acme_sh(ACME_HOME, ACME_BIN)
    subprocess.run([str(ACME_BIN), "--version"], check=True, capture_output=True, text=True)


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
    ca = acct.get("ca", "letsencrypt")
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


def box_state_dir(box_name: str) -> pathlib.Path:
    """Return the state directory for a given box."""
    state = STATE_ROOT / box_name
    state.mkdir(parents=True, exist_ok=True)
    return state


def issue_certificate(
    box_name: str,
    domain: str,
    dns_plugin: str,
    dns_credentials: Dict[str, str],
    key_type: str = "2048",
) -> None:
    """
    Issue (or re-issue) a certificate for the given box using acme.sh DNS provider.
    dns_plugin examples: 'dns_gd', 'dns_cf', 'dns_ionos', ...
    """
    # 1) Ensure acme.sh exists, then ensure account/CA
    ensure_acme_installed()
    ensure_account()

    # 2) Resolve output paths and provider env
    state_dir = box_state_dir(box_name)
    key_path = state_dir / "fritzbox.key"
    pem_path = state_dir / "fritzbox.pem"

    cfg = _load_global_yaml()
    server = (cfg.get("account", {}) or {}).get("ca", "letsencrypt")
    if server not in ACCEPTED_CAS:
        server = "letsencrypt"

    # Environment for provider (e.g., GD_Key, CF_Token, IONOS_API_KEY, ...)
    dns_props = dns_credentials or {}
    env = {k: str(v) for k, v in dns_props.items()}
    print(f"[issue] domain={domain} provider={dns_plugin} ca={server} creds={list(env.keys())}")

    # 3) Issue
    issue_args = ["--issue", "--dns", dns_plugin, "-d", domain, "--keylength", str(key_type), "--server", server]
    res = _run_acme(issue_args, extra_env=env, check=False)
    if res.returncode != 0:
        raise AcmeError(
            f"acme.sh --issue failed (rc={res.returncode})\n"
            f"STDOUT:\n{res.stdout}\n\nSTDERR:\n{res.stderr}"
        )

    # 4) Install cert (key + fullchain) into our managed state dir
    inst = _run_acme(
        ["--install-cert", "-d", domain, "--key-file", str(key_path), "--fullchain-file", str(pem_path)],
        check=False,
    )
    if inst.returncode != 0:
        raise AcmeError(
            f"acme.sh --install-cert failed (rc={inst.returncode})\n"
            f"STDOUT:\n{inst.stdout}\n\nSTDERR:\n{inst.stderr}"
        )

    os.chmod(key_path, 0o600)
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
        return None


def show_status(box_name: str) -> None:
    """Print local cert/key paths and expiry for the given box."""
    pem = (STATE_ROOT / box_name) / "fritzbox.pem"
    key = (STATE_ROOT / box_name) / "fritzbox.key"
    if not pem.exists():
        print(f"[{box_name}] No certificate found.")
        return
    exp = check_certificate_expiry(pem) or "unknown"
    print(f"[{box_name}] Certificate: {pem}")
    print(f"  Key: {key}")
    print(f"  Expires: {exp}")
