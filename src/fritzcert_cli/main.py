"""
main.py – CLI entry point for fritzcert
"""

from __future__ import annotations
import argparse
import getpass
import sys
import pathlib
import os
import stat
import tempfile
import shutil
import subprocess

from fritzcert_cli import config, acme, fritzbox


def _resolve_log_file() -> pathlib.Path:
    """
    Decide on a writable log location.
    Prefer system path when available, otherwise fall back to the user's state dir.
    """
    candidates = [pathlib.Path("/var/log/fritzcert")]

    try:
        home_dir = pathlib.Path.home()
    except RuntimeError:
        home_dir = None

    if home_dir:
        candidates.append(home_dir / ".local/state/fritzcert")
    for directory in candidates:
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


def log(msg: str) -> None:
    line = f"[{os.getpid()}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _configure_completion(parser: argparse.ArgumentParser, subparsers: argparse._SubParsersAction) -> None:
    """Enable argcomplete autocomplete with subcommand suggestions."""
    try:
        import argcomplete  # type: ignore
        from argcomplete.completers import ChoicesCompleter  # type: ignore
    except ImportError:
        return

    subparsers.completer = ChoicesCompleter(list(subparsers.choices.keys()))
    argcomplete.autocomplete(parser)


def _box_name_completer(prefix: str, parsed_args, **_unused):
    """Return matching box names for completion."""
    try:
        boxes = config.list_boxes()
    except Exception:
        return []
    names = [b.get("name", "") for b in boxes if isinstance(b, dict)]
    return [name for name in names if isinstance(name, str) and name.startswith(prefix)]


def _default_completion_path(shell: str) -> pathlib.Path:
    """Return default install path for completion scripts based on shell."""
    if shell == "bash":
        if os.geteuid() == 0:
            return pathlib.Path("/etc/bash_completion.d/fritzcert")
        return pathlib.Path.home() / ".local/share/bash-completion/completions/fritzcert"
    if shell == "zsh":
        if os.geteuid() == 0:
            return pathlib.Path("/usr/local/share/zsh/site-functions/_fritzcert")
        return pathlib.Path.home() / ".local/share/zsh/site-functions/_fritzcert"
    raise ValueError(f"Unsupported shell: {shell}")


def _generate_completion_script(shell: str) -> str:
    """Generate completion script content via argcomplete."""
    cmd = [
        sys.executable,
        "-m",
        "argcomplete.scripts.register_python_argcomplete",
        "--shell",
        shell,
        "fritzcert",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("argcomplete is not available in the current environment.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(f"Failed to generate completion script: {stderr}") from exc
    return proc.stdout


def _ensure_profile_hook(shell: str, dest_path: pathlib.Path) -> None:
    """Ensure the user's shell profile sources the completion script."""
    marker = f"# >>> fritzcert {shell} completion >>>"
    end_marker = f"# <<< fritzcert {shell} completion <<<"
    snippet = f"""{marker}
if [ -f "{dest_path}" ]; then
    source "{dest_path}"
fi
{end_marker}
"""
    if shell == "bash":
        profile = pathlib.Path.home() / ".bashrc"
    elif shell == "zsh":
        profile = pathlib.Path.home() / ".zshrc"
    else:
        return

    try:
        existing = profile.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""

    if marker in existing:
        return

    profile.parent.mkdir(parents=True, exist_ok=True)
    with open(profile, "a", encoding="utf-8") as fh:
        if existing and not existing.endswith("\n"):
            fh.write("\n")
        fh.write(snippet)


def cmd_init(args):
    """Create a configuration file with the 'account' section (email required)."""
    config.ensure_dirs()
    if not config.CONFIG_PATH.exists():
        body = (
            "account:\n"
            f"  ca: {args.ca}\n"
            f"  email: {args.email}\n"
            "boxes: []\n"
        )
        config.CONFIG_PATH.write_text(body, encoding="utf-8")
        try:
            os.chmod(config.CONFIG_PATH, config.SECURE_FILE_MODE)
        except PermissionError as exc:
            raise config.ConfigError(
                f"Unable to set secure permissions on {config.CONFIG_PATH}: {exc}"
            ) from exc
        log(f"Created configuration file: {config.CONFIG_PATH}")
    else:
        # If it exists, update/add the account section while preserving the rest
        data = config._load_yaml()  # reuse internal
        data.setdefault("account", {})
        data["account"]["ca"] = args.ca
        data["account"]["email"] = args.email
        config._save_yaml(data)
        log("Existing config: updated 'account' section.")
    print(f"Configuration at {config.CONFIG_PATH}")


def cmd_list(args):
    boxes = config.list_boxes()
    if not boxes:
        print("No Fritz!Box configured.")
        return
    for b in boxes:
        print(f"- {b['name']}: {b['domain']} ({b['dns_provider']['plugin']})")


def _assert_secret_file(path: pathlib.Path, label: str) -> pathlib.Path:
    """Ensure secret file exists with owner-only permissions."""
    try:
        st = path.stat()
    except FileNotFoundError as exc:
        raise RuntimeError(f"{label} file not found: {path}") from exc
    except PermissionError as exc:
        raise RuntimeError(f"Unable to read metadata for {label} file {path}: {exc}") from exc

    mode = stat.S_IMODE(st.st_mode)
    if mode & 0o077:
        raise RuntimeError(f"{label} file {path} must not be accessible by group or others (use chmod 600).")
    return path


def _load_secret_kv_file(path: pathlib.Path, label: str) -> dict[str, str]:
    """Parse KEY=VALUE pairs from a secret file."""
    secret_path = _assert_secret_file(path, label)
    content = secret_path.read_text(encoding="utf-8")
    data: dict[str, str] = {}
    for idx, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise RuntimeError(f"{label} file {secret_path} line {idx} is missing '='.")
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise RuntimeError(f"{label} file {secret_path} line {idx} has an empty key.")
        if not value:
            raise RuntimeError(f"{label} file {secret_path} line {idx} has an empty value.")
        data[key] = value
    if not data:
        raise RuntimeError(f"{label} file {secret_path} does not contain any credentials.")
    return data


def _read_secret_value(path: pathlib.Path, label: str) -> str:
    """Read a single secret (password/token) from a file."""
    secret_path = _assert_secret_file(path, label)
    value = secret_path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"{label} file {secret_path} is empty.")
    return value


def _resolve_secret_descriptor(raw: str, label: str) -> str:
    """
    Interpret special descriptors for secrets:
    - "?" -> prompt via getpass
    - "@env:VAR" -> use environment variable VAR
    - otherwise return value as-is
    """
    descriptor = raw.strip()
    if descriptor == "?":
        if not sys.stdin.isatty():
            raise RuntimeError(f"{label} prompt requires an interactive terminal.")
        value = getpass.getpass(f"{label}: ")
        if not value:
            raise RuntimeError(f"{label} cannot be empty.")
        return value
    if descriptor.startswith("@env:"):
        env_var = descriptor[len("@env:") :].strip()
        if not env_var:
            raise RuntimeError(f"{label} environment variable name is empty.")
        value = os.environ.get(env_var)
        if value is None:
            raise RuntimeError(f"{label} environment variable '{env_var}' is not set.")
        if not value:
            raise RuntimeError(f"{label} environment variable '{env_var}' is empty.")
        return value
    return descriptor


def cmd_add_box(args):
    raw_dns_entries: list[str] = []

    if args.dns_cred:
        for group in args.dns_cred:
            raw_dns_entries.extend(group)

    if raw_dns_entries and args.dns_cred_file:
        print("Use either --dns-cred or --dns-cred-file (not both).", file=sys.stderr)
        sys.exit(1)

    dns_credentials: dict[str, str] = {}
    if args.dns_cred_file:
        try:
            dns_credentials = _load_secret_kv_file(
                pathlib.Path(args.dns_cred_file).expanduser(),
                "DNS credential",
            )
        except RuntimeError as exc:
            print(f"{exc}", file=sys.stderr)
            sys.exit(1)
    elif raw_dns_entries:
        insecure_keys: set[str] = set()
        for kv in raw_dns_entries:
            if "=" not in kv:
                print(f"Invalid parameter: {kv}", file=sys.stderr)
                sys.exit(1)
            key, raw_value = kv.split("=", 1)
            key = key.strip()
            if not key:
                print(f"Invalid credential key in '{kv}'", file=sys.stderr)
                sys.exit(1)
            raw_value = raw_value.strip()
            try:
                resolved = _resolve_secret_descriptor(raw_value, f"{key} credential")
            except RuntimeError as exc:
                print(f"{exc}", file=sys.stderr)
                sys.exit(1)
            if resolved == raw_value:
                insecure_keys.add(key)
            dns_credentials[key] = resolved
        if insecure_keys:
            log(
                "NOTE: DNS credentials provided directly via CLI arguments for keys: "
                + ", ".join(sorted(insecure_keys))
            )

    fritz_password: str
    if args.fritz_pass and args.fritz_pass_file:
        print("Use either --fritz-pass or --fritz-pass-file (not both).", file=sys.stderr)
        sys.exit(1)

    try:
        if args.fritz_pass_file:
            fritz_password = _read_secret_value(
                pathlib.Path(args.fritz_pass_file).expanduser(),
                "Fritz!Box password",
            )
        elif args.fritz_pass:
            fritz_password = _resolve_secret_descriptor(args.fritz_pass, "Fritz!Box password")
            if fritz_password == args.fritz_pass:
                log("NOTE: Fritz!Box password provided directly via CLI argument (visible in process table).")
        else:
            if not sys.stdin.isatty():
                print(
                    "Fritz!Box password required but stdin is not interactive. "
                    "Use --fritz-pass-file or --fritz-pass @env:VAR.",
                    file=sys.stderr,
                )
                sys.exit(1)
            fritz_password = getpass.getpass("Fritz!Box password: ")
            if not fritz_password:
                print("Fritz!Box password cannot be empty.", file=sys.stderr)
                sys.exit(1)
    except RuntimeError as exc:
        print(f"{exc}", file=sys.stderr)
        sys.exit(1)

    fritz_conf = {
        "url": args.fritz_url,
        "username": args.fritz_user,
        "password": fritz_password,
    }
    if args.fritz_ca_file:
        fritz_conf["ca_cert"] = os.path.expanduser(args.fritz_ca_file)
    if args.allow_insecure_tls:
        fritz_conf["allow_insecure"] = True

    config.add_or_update_box(
        name=args.name,
        domain=args.domain,
        dns_plugin=args.dns_plugin,
        dns_credentials=dns_credentials,
        fritzbox=fritz_conf,
        key_type=args.key_type,
    )
    log(f"Added box {args.name}")
    print(f"Box '{args.name}' added successfully.")


def cmd_remove_box(args):
    config.remove_box(args.name)
    print(f"Box '{args.name}' removed.")
    log(f"Removed box {args.name}")


def cmd_issue(args):
    boxes = config.list_boxes()
    if args.name:
        boxes = [b for b in boxes if b["name"] == args.name]
    if not boxes:
        print("No box found to issue.")
        sys.exit(1)

    for b in boxes:
        dns = b["dns_provider"]
        creds = dns.get("credentials", {})
        log(f"Issuing certificate for {b['name']} ({b['domain']})")
        try:
            acme.issue_certificate(
                box_name=b["name"],
                domain=b["domain"],
                dns_plugin=dns["plugin"],
                dns_credentials=creds,
                key_type=b.get("key_type", "2048"),
            )
        except Exception as e:
            log(f"Issue error for {b['name']}: {e}")
            print(f"Error on {b['name']}: {e}")


def cmd_deploy(args):
    boxes = config.list_boxes()
    if args.name:
        boxes = [b for b in boxes if b["name"] == args.name]
    if not boxes:
        print("No box found to deploy.")
        sys.exit(1)

    for b in boxes:
        state_dir = pathlib.Path("/var/lib/fritzcert") / b["name"]
        try:
            log(f"Deploy to {b['name']}")
            fritzbox.deploy_certificate(b["name"], b["fritzbox"], state_dir)
        except Exception as e:
            log(f"Deploy error for {b['name']}: {e}")
            print(f"Deploy failed on {b['name']}: {e}")


def cmd_renew(args):
    try:
        acme.renew_all_certificates()
        print("Renewal completed.")
        log("Renewal completed.")
    except Exception as e:
        log(f"Renew error: {e}")
        print(f"Renew error: {e}")


def cmd_status(args):
    boxes = config.list_boxes()
    for b in boxes:
        acme.show_status(b["name"])


def cmd_install_systemd(args):
    """Install a systemd service and timer for daily automatic renewal and deploy."""
    user = os.environ.get("SUDO_USER") or os.environ.get("USER", "root")
    svc = "/etc/systemd/system/fritzcert.service"
    tim = "/etc/systemd/system/fritzcert.timer"
    fritzcert_exec = shutil.which("fritzcert") or "/usr/local/bin/fritzcert"
    svc_body = f"""[Unit]
Description=Renew Let's Encrypt and deploy to Fritz!Box (fritzcert)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User={user}
ExecStart={fritzcert_exec} renew
ExecStartPost={fritzcert_exec} deploy
"""
    tim_body = """[Unit]
Description=Daily fritzcert renew + deploy

[Timer]
OnCalendar=daily
RandomizedDelaySec=1800
Persistent=true

[Install]
WantedBy=timers.target
"""
    pathlib.Path(svc).write_text(svc_body, encoding="utf-8")
    pathlib.Path(tim).write_text(tim_body, encoding="utf-8")
    os.system("systemctl daemon-reload")
    os.system("systemctl enable --now fritzcert.timer")
    print("Systemd timer installed: fritzcert.timer")


def cmd_install_completion(args):
    """Install shell completion script for fritzcert."""
    shell = args.shell
    try:
        script = _generate_completion_script(shell)
    except RuntimeError as exc:
        print(f"Unable to generate completion script: {exc}")
        sys.exit(1)

    dest_path = pathlib.Path(args.dest) if args.dest else _default_completion_path(shell)
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(script, encoding="utf-8")
        try:
            os.chmod(dest_path, 0o644)
        except PermissionError:
            pass
        if os.geteuid() != 0:
            try:
                _ensure_profile_hook(shell, dest_path)
            except OSError as exc:
                log(f"Unable to update profile for {shell} completion: {exc}")
        log(f"Installed {shell} completion at {dest_path}")
        print(f"{shell} completion installed at {dest_path}")
    except PermissionError:
        print(f"Permission denied writing completion script to {dest_path}. Try running with sudo.")
        sys.exit(1)
    except OSError as exc:
        print(f"Failed to write completion script: {exc}")
        sys.exit(1)


def cmd_register_account(args):
    """Update the account section in config and register with the selected CA."""
    try:
        config.set_account(args.ca, args.email)
    except config.ConfigError as e:
        print(f"{e}")
        sys.exit(1)

    try:
        acme.ensure_acme_installed()
        acme.ensure_account()
        print(f"Account registered: CA={args.ca}, email={args.email}")
    except Exception as e:
        print(f"Account saved to config, but ACME registration failed: {e}")
        print("You can retry with the same command or continue with 'fritzcert issue'.")


def main():
    p = argparse.ArgumentParser(
        prog="fritzcert",
        description="Automated Let's Encrypt certificate management for multiple Fritz!Box devices",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    initp = sub.add_parser("init", help="Create an empty configuration file (requires CA email)")
    initp.add_argument("--email", required=True, help="Email for the CA account (used by acme.sh)")
    initp.add_argument("--ca", default="letsencrypt", choices=["letsencrypt", "zerossl"], help="Certificate Authority")

    sub.add_parser("list", help="List configured Fritz!Box entries")

    reg = sub.add_parser("register-account", help="Set CA and email and register the ACME account")
    reg.add_argument("--email", required=True, help="Email for the ACME account (required)")
    reg.add_argument("--ca", default="letsencrypt", choices=["letsencrypt", "zerossl"], help="Certificate Authority")

    add = sub.add_parser("add-box", help="Add or update a Fritz!Box entry")
    add.add_argument("--name", required=True, help="Internal name for the Fritz!Box")
    add.add_argument("--domain", required=True, help="Domain to issue the certificate for")
    add.add_argument("--dns-plugin", required=True, help="acme.sh DNS plugin (e.g., dns_gd, dns_cf)")
    add.add_argument(
        "--dns-cred",
        metavar="KEY=VALUE",
        action="append",
        nargs="+",
        help="DNS credentials as KEY=VALUE pairs. Use VALUE='?' to prompt, VALUE='@env:VAR' to read from environment.",
    )
    add.add_argument(
        "--dns-cred-file",
        help="File containing DNS credentials (KEY=VALUE per line, chmod 600).",
    )
    add.add_argument("--fritz-url", required=True, help="Full URL (e.g., https://router.example.ch)")
    add.add_argument("--fritz-user", required=True, help="Fritz!Box username")
    add.add_argument(
        "--fritz-pass",
        help="Fritz!Box password. Use '?' to prompt or '@env:VAR' to read from an environment variable.",
    )
    add.add_argument(
        "--fritz-pass-file",
        help="File containing the Fritz!Box password (chmod 600).",
    )
    add.add_argument(
        "--fritz-ca-file",
        help="Custom CA bundle to trust when connecting to the Fritz!Box.",
    )
    add.add_argument(
        "--allow-insecure-tls",
        action="store_true",
        help="Disable TLS verification for Fritz!Box connections (not recommended).",
    )
    add.add_argument("--key-type", default="2048", help="Key type (2048, ec-256, etc.)")

    rem = sub.add_parser("remove-box", help="Remove a Fritz!Box entry")
    rem_name = rem.add_argument("--name", required=True)
    rem_name.completer = _box_name_completer

    iss = sub.add_parser("issue", help="Issue or renew certificates")
    iss_name = iss.add_argument("--name", help="Limit to a specific Fritz!Box")
    iss_name.completer = _box_name_completer

    dep = sub.add_parser("deploy", help="Deploy certificate to Fritz!Box")
    dep_name = dep.add_argument("--name", help="Limit to a specific Fritz!Box")
    dep_name.completer = _box_name_completer

    sub.add_parser("renew", help="Run renewal for all certificates")
    sub.add_parser("status", help="Show certificate status")
    sub.add_parser("install-systemd", help="Install the daily systemd timer")
    comp = sub.add_parser("install-completion", help="Install shell completion script")
    comp.add_argument("--shell", default="bash", choices=["bash", "zsh"], help="Target shell (default: bash)")
    comp.add_argument("--dest", help="Custom destination path for the completion file")

    _configure_completion(p, sub)

    args = p.parse_args()

    cmd_map = {
        "init": cmd_init,
        "register-account": cmd_register_account,
        "list": cmd_list,
        "add-box": cmd_add_box,
        "remove-box": cmd_remove_box,
        "issue": cmd_issue,
        "deploy": cmd_deploy,
        "renew": cmd_renew,
        "status": cmd_status,
        "install-systemd": cmd_install_systemd,
        "install-completion": cmd_install_completion,
    }
    fn = cmd_map.get(args.cmd)
    if fn:
        fn(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
