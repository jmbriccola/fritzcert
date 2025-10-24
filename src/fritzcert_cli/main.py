"""
main.py – Entry point CLI per fritzcert
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
    """Crea un file di configurazione con la sezione account (email obbligatoria)."""
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
        log(f"Creato file di configurazione: {config.CONFIG_PATH}")
    else:
        # se esiste, aggiorna/aggiungi la sezione account mantenendo il resto
        data = config._load_yaml()  # reuse internal
        data.setdefault("account", {})
        data["account"]["ca"] = args.ca
        data["account"]["email"] = args.email
        config._save_yaml(data)
        log("Config già presente: aggiornata sezione 'account'.")
    print(f"Configurazione in {config.CONFIG_PATH}")


def cmd_list(args):
    boxes = config.list_boxes()
    if not boxes:
        print("Nessun Fritz!Box configurato.")
        return
    for b in boxes:
        print(f"- {b['name']}: {b['domain']} ({b['dns_provider']['plugin']})")


def cmd_add_box(args):
    dns_credentials = {}
    if args.dns_cred:
        for kv in args.dns_cred:
            if "=" not in kv:
                print(f"Parametro errato: {kv}")
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
    log(f"Aggiunto box {args.name}")
    print(f"Box '{args.name}' aggiunto con successo.")


def cmd_remove_box(args):
    config.remove_box(args.name)
    print(f"Box '{args.name}' rimosso.")
    log(f"Rimosso box {args.name}")


def cmd_issue(args):
    boxes = config.list_boxes()
    if args.name:
        boxes = [b for b in boxes if b["name"] == args.name]
    if not boxes:
        print("Nessun box trovato per l’emissione.")
        sys.exit(1)

    for b in boxes:
        dns = b["dns_provider"]
        creds = dns.get("credentials", {})
        log(f"Emissione certificato per {b['name']} ({b['domain']})")
        try:
            acme.issue_certificate(
                box_name=b["name"],
                domain=b["domain"],
                dns_plugin=dns["plugin"],
                dns_credentials=creds,
                key_type=b.get("key_type", "2048"),
            )
        except Exception as e:
            log(f"Errore emissione {b['name']}: {e}")
            print(f"❌ Errore su {b['name']}: {e}")


def cmd_deploy(args):
    boxes = config.list_boxes()
    if args.name:
        boxes = [b for b in boxes if b["name"] == args.name]
    if not boxes:
        print("Nessun box trovato per deploy.")
        sys.exit(1)

    for b in boxes:
        state_dir = pathlib.Path("/var/lib/fritzcert") / b["name"]
        try:
            log(f"Deploy su {b['name']}")
            fritzbox.deploy_certificate(b["name"], b["fritzbox"], state_dir)
        except Exception as e:
            log(f"Errore deploy {b['name']}: {e}")
            print(f"❌ Deploy fallito su {b['name']}: {e}")


def cmd_renew(args):
    try:
        acme.renew_all_certificates()
        print("✅ Rinnovo completato.")
        log("Rinnovo completato.")
    except Exception as e:
        log(f"Errore rinnovo: {e}")
        print(f"❌ Errore rinnovo: {e}")


def cmd_status(args):
    boxes = config.list_boxes()
    for b in boxes:
        acme.show_status(b["name"])


def cmd_install_systemd(args):
    """Crea un service+timer systemd per rinnovo automatico."""
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
    print("✅ Timer systemd installato: fritzcert.timer")


def cmd_register_account(args):
    """Aggiorna la sezione account nel config e registra presso la CA scelta."""
    try:
        config.set_account(args.ca, args.email)
    except config.ConfigError as e:
        print(f"❌ {e}")
        sys.exit(1)

    try:
        acme.ensure_acme_installed()
        acme.ensure_account()
        print(f"✅ Account registrato: CA={args.ca}, email={args.email}")
    except Exception as e:
        print(f"⚠️  Account impostato nel config, ma registrazione ACME fallita: {e}")
        print("   Puoi riprovare con lo stesso comando o proseguire con 'fritzcert issue'.")


def main():
    p = argparse.ArgumentParser(
        prog="fritzcert",
        description="Gestione automatica dei certificati Let's Encrypt per più Fritz!Box",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    initp = sub.add_parser("init", help="Crea un file di configurazione vuoto (richiede email per il CA)")
    initp.add_argument("--email", required=True, help="Email account per il CA (usata da acme.sh)")
    initp.add_argument("--ca", default="letsencrypt", choices=["letsencrypt", "zerossl"], help="Certificate Authority")
    sub.add_parser("list", help="Elenca i Fritz!Box configurati")

    reg = sub.add_parser("register-account", help="Imposta CA ed email e registra l'account ACME")
    reg.add_argument("--email", required=True, help="Email per l'account ACME (obbligatoria)")
    reg.add_argument("--ca", default="letsencrypt", choices=["letsencrypt", "zerossl"], help="Certificate Authority")

    add = sub.add_parser("add-box", help="Aggiunge o aggiorna un Fritz!Box")
    add.add_argument("--name", required=True, help="Nome interno del Fritz!Box")
    add.add_argument("--domain", required=True, help="Dominio per il certificato")
    add.add_argument("--dns-plugin", required=True, help="Plugin DNS di acme.sh (es: dns_gd, dns_cf)")
    add.add_argument("--dns-cred", nargs="*", help="Credenziali DNS in forma CHIAVE=VALORE")
    add.add_argument("--fritz-url", required=True, help="URL completo (es: https://router.dominio.ch)")
    add.add_argument("--fritz-user", required=True, help="Username Fritz!Box")
    add.add_argument("--fritz-pass", required=True, help="Password Fritz!Box")
    add.add_argument("--key-type", default="2048", help="Tipo chiave (2048, ec-256, ecc.)")

    rem = sub.add_parser("remove-box", help="Rimuove un Fritz!Box")
    rem.add_argument("--name", required=True)

    iss = sub.add_parser("issue", help="Emette o rinnova certificati")
    iss.add_argument("--name", help="Limita a un Fritz!Box specifico")

    dep = sub.add_parser("deploy", help="Carica certificato sui Fritz!Box")
    dep.add_argument("--name", help="Limita a un Fritz!Box specifico")

    sub.add_parser("renew", help="Esegue rinnovo certificati (tutti i domini)")
    sub.add_parser("status", help="Mostra stato certificati")
    sub.add_parser("install-systemd", help="Installa il timer systemd giornaliero")

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
