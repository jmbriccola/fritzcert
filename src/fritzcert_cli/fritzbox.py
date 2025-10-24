from __future__ import annotations
import subprocess
import hashlib
import xml.etree.ElementTree as ET
from typing import Optional
import tempfile
import os
import pathlib


class FritzBoxError(RuntimeError):
    pass


def _curl(args: list[str]) -> str:
    res = subprocess.run(["curl", "-sk"] + args, capture_output=True, text=True)
    if res.returncode != 0:
        raise FritzBoxError(f"curl error: {res.stderr.strip()}")
    return res.stdout


def get_sid(base_url: str, username: str, password: str) -> str:
    base = base_url.rstrip("/")
    xml = _curl([f"{base}/login_sid.lua"])
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise FritzBoxError("Invalid XML response from login_sid.lua")

    sid = root.findtext("SID")
    if sid and sid != "0000000000000000":
        return sid

    challenge = root.findtext("Challenge")
    if not challenge:
        raise FritzBoxError("Challenge not found in login_sid.lua")

    raw = f"{challenge}-{password}".encode("utf-16le")
    md5 = hashlib.md5(raw).hexdigest()
    response = f"{challenge}-{md5}"

    xml2 = _curl([f"{base}/login_sid.lua?username={username}&response={response}"])
    root2 = ET.fromstring(xml2)
    sid = root2.findtext("SID")
    if not sid or sid == "0000000000000000":
        raise FritzBoxError("FRITZ!Box authentication failed.")
    return sid


# === Method 1: newer endpoint (already used) ===============================
def upload_cert_certificate_upload_lua(base_url: str, sid: str, pem_file: pathlib.Path, key_file: pathlib.Path) -> None:
    base = base_url.rstrip("/")
    if not pem_file.exists() or not key_file.exists():
        raise FritzBoxError("Certificate or key file not found.")

    # Note: on some firmware versions this uploads but does not activate
    _ = _curl([
        "-F", f"sid={sid}",
        "-F", f"boxcert=@{pem_file};type=application/x-x509-ca-cert",
        "-F", f"boxkey=@{key_file};type=application/octet-stream",
        f"{base}/system/certificate_upload.lua",
    ])


# === Method 2: legacy endpoint matching the Web UI (firmwarecfg) ==========
def upload_cert_firmwarecfg(base_url: str, sid: str, pem_file: pathlib.Path, key_file: pathlib.Path, cert_password: str = "") -> None:
    """
    Emulates the Web UI import:
    - single "BoxCertImportFile" containing key + fullchain (in this order)
    - optional "BoxCertPassword" (empty for unencrypted PEM)
    """
    base = base_url.rstrip("/")
    if not pem_file.exists() or not key_file.exists():
        raise FritzBoxError("Certificate or key file not found.")

    # Build a temporary file with key + fullchain in the order expected by the UI
    data = key_file.read_bytes() + pem_file.read_bytes()
    with tempfile.NamedTemporaryFile(prefix="fritzcert_", suffix=".pem", delete=False) as tmp:
        tmp.write(data)
        tmp.flush()
        tmp_path = pathlib.Path(tmp.name)

    try:
        # Use --form exactly like the UI: fields first, then the URL
        out = _curl([
            "--form", f"sid={sid}",
            "--form", f"BoxCertPassword={cert_password}",
            "--form", f"BoxCertImportFile=@{tmp_path};filename=BoxCert.pem;type=application/octet-stream",
            f"{base}/cgi-bin/firmwarecfg",
        ])
        # Some firmware does not print a clear "successful" indicator; don't hard-fail if missing
        if "error" in out.lower():
            raise FritzBoxError(f"firmwarecfg response: {out.strip()}")
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


def deploy_certificate(
    box_name: str,
    fritz_conf: dict,
    state_dir: pathlib.Path
) -> None:
    url = fritz_conf.get("url")
    user = fritz_conf.get("username")
    pwd = fritz_conf.get("password")
    cert_password = fritz_conf.get("cert_password", "")  # optional

    if not url or not user or not pwd:
        raise FritzBoxError(f"Incomplete FRITZ!Box configuration for '{box_name}'.")

    key_file = state_dir / "fritzbox.key"
    pem_file = state_dir / "fritzbox.pem"

    sid = get_sid(url, user, pwd)

    print("Upload (method 1) certificate_upload.lua ...")
    try:
        upload_cert_certificate_upload_lua(url, sid, pem_file, key_file)
    except Exception as e:
        print(f"Method 1 failed: {e}")

    print("Upload (method 2) firmwarecfg ...")
    try:
        upload_cert_firmwarecfg(url, sid, pem_file, key_file, cert_password=cert_password)
    except Exception as e:
        # If method 2 fails as well, abort
        raise FritzBoxError(f"firmwarecfg upload failed: {e}")

    print("Deploy completed")
