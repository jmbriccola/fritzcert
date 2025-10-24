"""
main.py – CLI entry point for fritzcert
"""

from __future__ import annotations
import argparse
import sys
import pathlib
import os

from fritzcert_cli import config, acme, fritzbox

LOG_DIR = pathlib.Path("/var/log/fritzcert")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "fritzcert.log"


def log(msg: str):
    line = f"[{os.getpid()}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


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
        os.chmod(config.CONFIG_PATH, 0o640)
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


def cmd_add_box(args):
    dns_credentials = {}
    if args.dns_cred:
        for kv in args.dns_cred:
            if "=" not in kv:
                print(f"Invalid parameter: {kv}")
                sys.exit(1)
            k, v = kv.split("=", 1)
            dns_credentials[k] = v

    fritz_conf = {
        "url": args.fritz_url,
        "username": args.fritz_user,
        "password": args.fritz_pass,
    }

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
    svc_body = f"""[Unit]
Description=Renew Let's Encrypt and deploy to Fritz!Box (fritzcert)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User={user}
ExecStart=/usr/bin/fritzcert renew
ExecStartPost=/usr/bin/fritzcert deploy
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
    add.add_argument("--dns-cred", nargs="*", help="DNS credentials as KEY=VALUE pairs")
    add.add_argument("--fritz-url", required=True, help="Full URL (e.g., https://router.example.ch)")
    add.add_argument("--fritz-user", required=True, help="Fritz!Box username")
    add.add_argument("--fritz-pass", required=True, help="Fritz!Box password")
    add.add_argument("--key-type", default="2048", help="Key type (2048, ec-256, etc.)")

    rem = sub.add_parser("remove-box", help="Remove a Fritz!Box entry")
    rem.add_argument("--name", required=True)

    iss = sub.add_parser("issue", help="Issue or renew certificates")
    iss.add_argument("--name", help="Limit to a specific Fritz!Box")

    dep = sub.add_parser("deploy", help="Deploy certificate to Fritz!Box")
    dep.add_argument("--name", help="Limit to a specific Fritz!Box")

    sub.add_parser("renew", help="Run renewal for all certificates")
    sub.add_parser("status", help="Show certificate status")
    sub.add_parser("install-systemd", help="Install the daily systemd timer")

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
    }
    fn = cmd_map.get(args.cmd)
    if fn:
        fn(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
