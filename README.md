# fritzcert-cli
### Automated Let's Encrypt certificate management for multiple FRITZ!Box devices
_A command-line tool for issuing, deploying, and renewing SSL/TLS certificates via acme.sh._

---

## Overview

**fritzcert-cli** automates the complete lifecycle of HTTPS certificates for one or more **FRITZ!Box** routers:

- Issues certificates using **Let's Encrypt** or **ZeroSSL** through `acme.sh`.
- Supports any **DNS-01** provider supported by `acme.sh` (GoDaddy, Cloudflare, IONOS, AWS Route53, etc.).
- Automatically uploads and activates certificates on the FRITZ!Box via HTTPS API or firmware upload.
- Manages renewals and deployments automatically using **systemd** or cron.
- Fully configurable through `/etc/fritzcert/config.yaml`.
- Multi-device, multi-provider, multi-CA support.

---

## Features

- **Multi-CA** - Works with Let's Encrypt (default) or ZeroSSL.  
- **Multi-DNS Provider** - Compatible with any DNS-01 plugin supported by `acme.sh` (GoDaddy, Cloudflare, IONOS, AWS, etc.).  
- **Multi-Box Management** - Supports multiple FRITZ!Box routers, each with its own domain, DNS provider, and credentials.  
- **Automatic Renewal** - Daily certificate renewal and re-deployment via `systemd` timer or the built-in `acme.sh` cron.  
- **Secure Upload** - Certificates are uploaded to the FRITZ!Box using HTTPS and SID-based challenge authentication.  
- **Full Logging** - Unified logs under `/var/log/fritzcert/fritzcert.log` and visible through `journalctl`.  
- **Flexible Installation** - Works with `pipx` or standalone virtual environments under `/opt`.  
- **Readable Configuration** - YAML-based configuration stored in `/etc/fritzcert/config.yaml` with automatic backups.

---

## Architecture

The system consists of four main layers:

1. **Certificate Authority (CA)**  
   Handles certificate issuance through Let's Encrypt or ZeroSSL.

2. **acme.sh**  
   Performs DNS-01 validation using the configured DNS provider credentials (e.g., `GD_Key`, `CF_Token`, etc.).

3. **fritzcert-cli**  
   Orchestrates certificate issuance, deployment, and renewal. Integrates with acme.sh, manages configuration, and logs all operations.

4. **FRITZ!Box Web Interface**  
   The tool uploads the certificates to the router via HTTPS using either:
   - the official API (`system/certificate_upload.lua`), or  
   - the firmware configuration endpoint (`cgi-bin/firmwarecfg`), which activates the certificate immediately.

---

## Supported Platforms

- Debian / Ubuntu / Proxmox / Raspberry Pi OS  
- Any Linux system with **Python 3.10+**  
- FRITZ!Box routers supporting HTTPS remote administration (FRITZ!OS 7+ recommended)

---

## Installation & Setup

### Requirements

Before installing **fritzcert-cli**, make sure your environment meets the following requirements:

- **Python ≥ 3.10**
- **curl**, **bash**, **openssl** installed
- Optional: **systemd** (for automated daily renewal)
- A FRITZ!Box with **HTTPS access** enabled
- Root privileges (`sudo`) for initial setup

### Installing via Makefile (Recommended)

The Makefile automates the full setup, including pipx installation, building, and deployment.

```bash
sudo make install
```

This command will:

- Install `pipx` if it is missing
- Build a wheel for the current version
- Install `fritzcert-cli` globally using pipx
- Create `/usr/local/bin/fritzcert` symlink
- Create all required directories:
  - `/etc/fritzcert/`
  - `/var/lib/fritzcert/`
  - `/var/log/fritzcert/`

After installation, verify:

```bash
fritzcert --help
```

If you get `command not found`, ensure your pipx path is loaded:

```bash
pipx ensurepath
exec $SHELL
```

### Installing via Virtual Environment (Alternative)

If you prefer not to use `pipx`, you can install fritzcert-cli in a system virtual environment under `/opt`.

```bash
sudo make install-venv
```

This will:
- Create `/opt/fritzcert-cli-venv/`
- Install all dependencies
- Create a symlink `/usr/local/bin/fritzcert`

To uninstall:

```bash
sudo make uninstall
```

### Manual Wheel Build (Developers)

To build a standalone wheel package:

```bash
make build
```

The built package will appear under:

```
dist/fritzcert_cli-<version>-py3-none-any.whl
```

### Directory Structure

Once installed, fritzcert uses the following directories:

| Path | Description |
|------|--------------|
| `/etc/fritzcert/` | Global configuration and backups |
| `/var/lib/fritzcert/` | Certificates and private keys for each FRITZ!Box |
| `/var/log/fritzcert/` | Log files for all CLI operations |
| `/usr/local/bin/fritzcert` | CLI executable |

### Verifying the Installation

Run:

```bash
fritzcert --help
```

Expected output:

```
usage: fritzcert [-h] {init,list,add-box,remove-box,issue,deploy,renew,status,install-systemd} ...
```

If you see this output, the installation is complete.

---

## Configuration & Usage

### Global configuration file

**Location:** `/etc/fritzcert/config.yaml`

```yaml
account:
  ca: letsencrypt            # or zerossl
  email: you@example.com

boxes:
  - name: boxname
    domain: fritzbox.home.example.com
    key_type: 2048
    dns_provider:
      plugin: dns_gd
      credentials:
        GD_Key: "abc"
        GD_Secret: "def"
    fritzbox:
      url: https://fritzbox.home.example.com
      username: admin
      password: mypassword
      cert_password: ""      # optional
```

Notes:
- Each box may use a different DNS provider.
- Credential keys must match the variable names expected by the chosen `acme.sh` plugin (e.g., `GD_Key`, `GD_Secret`, `CF_Token`, `IONOS_API_KEY`, etc.).
- Supported key types: `2048`, `3072`, `4096`, `ec-256`, `ec-384`.

### DNS Provider Configuration

Each FRITZ!Box entry in `/etc/fritzcert/config.yaml` specifies a `dns_provider`.  
The `plugin` name corresponds directly to the **acme.sh DNS plugin**, and the `credentials`
section must define the environment variables required by that plugin.

Below are examples for the most commonly used DNS providers supported by acme.sh:

| Provider | Plugin name (`dns_plugin`) | Required credentials |
|-----------|----------------------------|----------------------|
| **GoDaddy** | `dns_gd` | `GD_Key` and `GD_Secret` |
| **Cloudflare (API Token)** | `dns_cf` | `CF_Token` |
| **Cloudflare (Global API Key)** | `dns_cf` | `CF_Key` and `CF_Email` |
| **IONOS (1&1)** | `dns_ionos` | `IONOS_API_KEY` and `IONOS_API_SECRET` |
| **AWS Route53** | `dns_aws` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` *(optional)* |
| **Google Cloud DNS** | `dns_gcloud` | `GOOGLE_APPLICATION_CREDENTIALS` (path to a JSON key file) |
| **DigitalOcean** | `dns_dgon` | `DO_API_KEY` |
| **Namecheap** | `dns_namecheap` | `NAMECHEAP_USERNAME` and `NAMECHEAP_API_KEY` |
| **OVH** | `dns_ovh` | `OVH_AK`, `OVH_AS`, `OVH_CK` |
| **Hetzner DNS** | `dns_hetzner` | `HETZNER_Token` |
| **Azure DNS** | `dns_azure` | `AZUREDNS_SUBSCRIPTIONID`, `AZUREDNS_TENANTID`, `AZUREDNS_APPID`, `AZUREDNS_CLIENTSECRET` |
| **DuckDNS** | `dns_duckdns` | `DuckDNS_Token` |
| **PowerDNS** | `dns_pdns` | `PDNS_Url`, `PDNS_ServerId`, `PDNS_Token` |
| **TransIP** | `dns_transip` | `TRANSIP_Username`, `TRANSIP_AccessToken` |
| **Dynu** | `dns_dynu` | `Dynu_ClientId`, `Dynu_Secret` |

> 💡 **Tip:** you can see all supported providers and their variables by running:  
> ```bash
> sudo /root/.acme.sh/acme.sh --list-dns
> ```

#### Example: Cloudflare API Token
```yaml
dns_provider:
  plugin: dns_cf
  credentials:
    CF_Token: "your_cloudflare_token"
```

#### Example: GoDaddy
```yaml
dns_provider:
  plugin: dns_gd
  credentials:
    GD_Key: "your_godaddy_key"
    GD_Secret: "your_godaddy_secret"
```

#### Example: AWS Route53
```yaml
dns_provider:
  plugin: dns_aws
  credentials:
    AWS_ACCESS_KEY_ID: "your_access_key"
    AWS_SECRET_ACCESS_KEY: "your_secret_key"
    AWS_REGION: "eu-central-1"
```

You can mix providers freely - each FRITZ!Box can use a different plugin and credentials.

### Initialize configuration

```bash
sudo fritzcert init --email you@example.com --ca letsencrypt
```

Creates or updates `/etc/fritzcert/config.yaml` with the chosen CA and email.

### Register ACME account

```bash
sudo fritzcert register-account --email you@example.com --ca zerossl
```

Sets CA + email and registers the account with acme.sh.

### List boxes

```bash
fritzcert list
```

### Add or update a box

```bash
sudo fritzcert add-box   --name office   --domain fritzbox.office.example.com   --dns-plugin dns_cf   --dns-cred CF_Token=cf_xxxxxxx   --fritz-url https://fritzbox.office.example.com   --fritz-user admin   --fritz-pass mysecret   --key-type ec-256
```

### Remove a box

```bash
sudo fritzcert remove-box --name office
```

### Issue or renew certificate for a box

```bash
sudo fritzcert issue --name office
```

- Generates the certificate via acme.sh (DNS-01).
- Installs it under `/var/lib/fritzcert/<box>/`.
- Uses the configured CA and DNS plugin.

### Deploy certificate to FRITZ!Box

```bash
sudo fritzcert deploy --name office
```

Uploads the key and certificate via:
1. `system/certificate_upload.lua` (API)  
2. Fallback: `cgi-bin/firmwarecfg` (Web UI import)

### Renew all certificates (on demand)

```bash
sudo fritzcert renew
```

### Show certificate status

```bash
fritzcert status
```

Displays certificate paths and expiry.

---

## Automatic Renewal & Deployment

### Option 1 - Systemd (recommended)

Install the service and timer:

```bash
sudo make install-systemd
```

This creates:
- `/etc/systemd/system/fritzcert.service`
- `/etc/systemd/system/fritzcert.timer`

Behavior:
- `fritzcert.service`: runs `fritzcert renew` then `fritzcert deploy`.
- `fritzcert.timer`: triggers the service daily with a randomized delay.

Check status and logs:

```bash
systemctl list-timers | grep fritzcert
journalctl -u fritzcert.service -n 50 --no-pager
```

### Option 2 - Cron (if systemd is unavailable)

Edit root crontab:

```bash
sudo crontab -e
```

Add a line (renew + deploy + log to file):

```cron
0 3 * * * /root/.acme.sh/acme.sh --cron --home "/root/.acme.sh" > /dev/null; /usr/local/bin/fritzcert deploy >> /var/log/fritzcert/cron.log 2>&1
```

---

## File Locations

| Path | Purpose |
|------|----------|
| `/etc/fritzcert/config.yaml` | Main configuration |
| `/var/lib/fritzcert/<box>/` | Stored key + certificate |
| `/var/log/fritzcert/fritzcert.log` | CLI logs |
| `/usr/local/bin/fritzcert` | Global CLI executable |

---

## Internal Components

| Component | Role |
|------------|------|
| `config.py` | Loads/saves YAML config, manages boxes, backups |
| `acme.py` | Integrates with `acme.sh` for issuance/renewal |
| `fritzbox.py` | Handles FRITZ!Box login, upload, and import |
| `main.py` | CLI entry point and argument parser |
| `utils.py` | Common logging and file utilities |
| `Makefile` | Build and installation automation |

---

## Security Notes

- Private keys are stored in `/var/lib/fritzcert/<box>/` with `600` permissions.
- Authentication uses the FRITZ!Box challenge-response SID mechanism.
- No passwords or API keys are written to logs.
- TLS uploads are performed over HTTPS (`curl -sk`).

---

## Troubleshooting

### Certificate not activated after upload
Use the firmwarecfg method (fallback). If it still shows self-signed:
- Ensure you are visiting the box via its **domain name** (`https://yourdomain.example.com`), not IP or `fritz.box`.
- Reboot the FRITZ!Box to reload the web server certificate.

### `acme.sh --issue` error mentioning EAB
You are using **ZeroSSL** without registering the account. Run:
```bash
sudo fritzcert register-account --email you@example.com --ca zerossl
```

### Permission denied creating `/etc/fritzcert`
Run setup commands with `sudo`.

### `fritzcert: command not found`
Ensure `pipx ensurepath` has been executed and reopen your shell, or create a global symlink:
```bash
sudo ln -sf ~/.local/bin/fritzcert /usr/local/bin/fritzcert
```

---

## Example Workflow

```bash
# 1. Initialize
sudo fritzcert init --email you@example.com --ca letsencrypt

# 2. Add box
sudo fritzcert add-box   --name home   --domain fritzbox.home.example.com   --dns-plugin dns_gd   --dns-cred GD_Key=xxxxx GD_Secret=yyyyy   --fritz-url https://fritzbox.home.example.com   --fritz-user admin   --fritz-pass mypassword

# 3. Issue
sudo fritzcert issue --name home

# 4. Deploy
sudo fritzcert deploy --name home

# 5. Enable auto-renew
sudo make install-systemd
```

---

## Makefile Commands

| Command | Description |
|----------|--------------|
| `make install` | Install via pipx (auto-installs pipx) |
| `make uninstall` | Remove fritzcert-cli |
| `make update` | Rebuild and reinstall |
| `make build` | Create `.whl` package |
| `make install-venv` | Install in /opt virtualenv |
| `make install-systemd` | Add daily renew+deploy systemd timer |
| `make uninstall-systemd` | Remove timer and service |
| `make clean` | Clean build and cache files |

---

## License

MIT License  
Copyright © 2025  
Author: Jacopo Maria Briccola

---

## Contributing

Pull requests are welcome. Please:
1. Follow PEP8 style.
2. Test on at least one FRITZ!Box model.

---

## Support

- GitHub: https://github.com/jmbriccola/fritzcert/issues
- Email: jmbriccola@gmail.com

---

Automate certificate management. Keep your FRITZ!Box secure - the easy way.