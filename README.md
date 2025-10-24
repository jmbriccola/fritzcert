# fritzcert-cli

Automated, security-focused management of public TLS certificates for one or more FRITZ!Box devices, powered by a curated integration with `acme.sh`.

The documentation below is intentionally exhaustive: every prerequisite, file, command and operational scenario is described to remove ambiguity during deployment and maintenance.

---

## 1. Quick Start (Minimum Viable Run)

```
# 1. Install prerequisites and the CLI
sudo make install

# 2. Create the global configuration with your ACME account
sudo fritzcert init --email you@example.com --ca letsencrypt

# 3. Register the ACME account (optional for Let's Encrypt, mandatory for ZeroSSL)
sudo fritzcert register-account --email you@example.com --ca letsencrypt

# 4. Add a FRITZ!Box definition (interactive prompts keep secrets off the command line)
export CF_TOKEN=cf_xxxxxxxx
sudo --preserve-env=CF_TOKEN fritzcert add-box \
  --name home \
  --domain fritzbox.example.com \
  --dns-plugin dns_cf \
  --dns-cred CF_Token=@env:CF_TOKEN \
  --fritz-url https://fritzbox.example.com \
  --fritz-user admin \
  --fritz-pass ? \
  --fritz-ca-file /etc/ssl/certs/ca-certificates.crt

# 5. Issue the certificate
sudo fritzcert issue --name home

# 6. Deploy the certificate to the FRITZ!Box
sudo fritzcert deploy --name home
```

After step 6, browse to `https://fritzbox.example.com` and verify that the FRITZ!Box presents a valid browser-trusted certificate.

---

## 2. Requirements

### 2.1 Operating system & tools

- Linux host (Debian, Ubuntu, Proxmox, Raspberry Pi OS, or any distribution with Python 3.10+)
- Utilities: `bash`, `curl`, `tar`, `openssl`, `systemctl` (for systemd automation), `cron` (optional)
- `sudo` privileges for installation and FRITZ!Box interactions that require root-owned directories

### 2.2 Python environment

- Python ≥ 3.10
- `pipx` (installed automatically by `make install` if missing)

### 2.3 FRITZ!Box prerequisites

- FRITZ!OS ≥ 7 recommended
- HTTPS access enabled on the FRITZ!Box
- Dedicated FRITZ!Box user/password for certificate administration
- (Optional) Custom CA certificate if the FRITZ!Box presents a private certificate that you want to pin

### 2.4 DNS provider prerequisites

- A DNS provider supported by `acme.sh` with API credentials capable of satisfying DNS-01 validation
- For ZeroSSL or other CAs requiring External Account Binding (EAB), obtain the EAB credentials prior to registration

---

## 3. Installation & Upgrade Paths

### 3.1 Recommended: Makefile + pipx (system-wide)

```
sudo make install
```

Actions performed:

1. Installs `pipx` (and `python3-venv`) if they are not present.
2. Builds the project wheel and installs it via `pipx`.
3. Creates symlink `/usr/local/bin/fritzcert`.
4. Creates required directories with secure permissions (`chmod 700`):
   - `/etc/fritzcert/`
   - `/etc/fritzcert/backups/`
   - `/var/lib/fritzcert/`
   - `/var/log/fritzcert/`
5. Installs shell completion for bash (and zsh when available).
6. Installs `fritzcert` systemd service and timer.

**acme.sh bootstrap**  
The first time you run any `fritzcert` command, the CLI downloads the pinned acme.sh release (`3.0.6` at the time of writing), verifies the SHA256 checksum (`4a8e44c27e2a8f01a978e8d15add8e9908b83f9b1555670e49a9b769421f5fa6`), and installs it under:

- `/root/.acme.sh/` when executed as root
- `$HOME/.acme.sh/` when executed as a non-root user

At no point is a remote script piped directly into `sh`.

### 3.2 Alternative: Dedicated virtual environment in `/opt`

```
sudo make install-venv
```

Creates `/opt/fritzcert-cli-venv/`, installs dependencies inside the virtual environment, and symlinks `/usr/local/bin/fritzcert`.

### 3.3 Developer workflow

```
make build       # produces wheel in dist/
pipx install dist/fritzcert_cli-<version>-py3-none-any.whl --force
```

To update an existing installation during development:

```
pipx reinstall fritzcert-cli .
```

### 3.4 Uninstalling

```
sudo make uninstall
```

This removes the pipx installation (if present), deletes `/opt/fritzcert-cli-venv/`, and removes `/usr/local/bin/fritzcert`. Configuration, certificates, and logs are left untouched.

---

## 4. Directory Layout & Permissions

| Path | Owner | Permissions | Purpose |
|------|-------|-------------|---------|
| `/etc/fritzcert/config.yaml` | root | `600` | Main YAML configuration |
| `/etc/fritzcert/backups/` | root | `700` | Timestamped backups of the configuration |
| `/var/lib/fritzcert/<box>/fritzbox.pem` | root | `600` | Full chain certificate for each box |
| `/var/lib/fritzcert/<box>/fritzbox.key` | root | `600` | Private key for each box |
| `/var/log/fritzcert/fritzcert.log` | root | `644` | Aggregated CLI output |
| `~/.acme.sh/` or `/root/.acme.sh/` | owner | `700` | acme.sh installation |

`fritzcert` enforces the secure permissions listed above whenever it writes the configuration or secrets. Do not loosen these permissions; commands will abort if group/other access is detected on secret files.

---

## 5. Configuration Model

### 5.1 Configuration file format

```
/etc/fritzcert/config.yaml

account:
  ca: letsencrypt      # or zerossl
  email: you@example.com

boxes:
  - name: home
    domain: fritzbox.example.com
    key_type: 2048
    dns_provider:
      plugin: dns_cf
      credentials:
        CF_Token: "...resolved secret..."
    fritzbox:
      url: https://fritzbox.example.com
      username: admin
      password: "...resolved secret..."
      cert_password: ""                 # optional (encrypted firmware uploads)
      ca_cert: /etc/ssl/certs/ca.pem    # optional path to CA bundle
      allow_insecure: false             # optional, default false
```

`fritzcert add-box` writes to this file; manual edits are possible but discouraged. Each modification triggers a backup under `/etc/fritzcert/backups/`.

### 5.2 Secret handling

CLI flags accept the following syntaxes for secrets:

| Syntax | Meaning | Example |
|--------|---------|---------|
| `?` | Prompt interactively using `getpass` | `--fritz-pass ?` |
| `@env:NAME` | Read from environment variable `NAME` | `--dns-cred CF_Token=@env:CF_TOKEN` |
| literal value | Use string as-is (least secure) | `--dns-cred CF_Token=mytoken` |
| `--*-file PATH` | Read from file (`chmod 600` required) | `--fritz-pass-file /root/pass.txt` |

When neither `--fritz-pass` nor `--fritz-pass-file` is supplied, `add-box` prompts automatically (if stdin is a TTY). Environment variables must be exported before invoking `fritzcert` and preserved when using `sudo`, e.g.:

```
export CF_TOKEN=cf_xxxxx
sudo --preserve-env=CF_TOKEN fritzcert add-box ...
```

### 5.3 TLS verification towards the FRITZ!Box

- By default, `fritzcert` verifies the FRITZ!Box HTTPS certificate.
- Provide `--fritz-ca-file` to pin a specific CA bundle if the FRITZ!Box is secured by a private CA.
- Set `--allow-insecure-tls` only as a last resort; it toggles `curl -k`.

### 5.4 Restoring from backup

```
sudo ls /etc/fritzcert/backups/
sudo cp /etc/fritzcert/backups/config-20250101-101530.yaml /etc/fritzcert/config.yaml
sudo chmod 600 /etc/fritzcert/config.yaml
```

---

## 6. Command Reference

### 6.1 Summary table

| Command | Purpose | Key options |
|---------|---------|-------------|
| `fritzcert init` | Create or update `/etc/fritzcert/config.yaml` account section | `--email`, `--ca` |
| `fritzcert register-account` | Register ACME account with the configured CA | `--email`, `--ca` |
| `fritzcert list` | Display configured boxes | n/a |
| `fritzcert add-box` | Add or update a FRITZ!Box definition | `--dns-plugin`, `--dns-cred`, `--fritz-pass`, TLS options |
| `fritzcert remove-box` | Delete a box from the configuration | `--name` |
| `fritzcert issue` | Issue/renew certificates via acme.sh | `--name` (optional) |
| `fritzcert deploy` | Upload and activate certificates on the FRITZ!Box | `--name` (optional) |
| `fritzcert renew` | Run acme.sh cron for all boxes | n/a |
| `fritzcert status` | Show local certificate paths and expiry | n/a |
| `fritzcert install-systemd` | Install service + timer for daily automation | n/a |
| `fritzcert install-completion` | Install shell completions | `--shell`, `--dest` |

Each command is detailed below with syntax, examples and expected output.

### 6.2 `fritzcert init`

- **Syntax**: `sudo fritzcert init --email EMAIL --ca {letsencrypt,zerossl}`
- **Creates** `/etc/fritzcert/config.yaml` if absent; otherwise only updates `account` section.
- **Output sample**:
  ```
  [26273] Created configuration file: /etc/fritzcert/config.yaml
  Configuration at /etc/fritzcert/config.yaml
  ```
- **Notes**: Ensures config directories exist (`chmod 700`) and sets file mode to `600`.

### 6.3 `fritzcert register-account`

- **Syntax**: `sudo fritzcert register-account --email EMAIL --ca CA`
- **Purpose**: Idempotent registration with acme.sh. Safe to run multiple times.
- **Output sample**:
  ```
  Account registered: CA=letsencrypt, email=you@example.com
  ```
- **Failure handling**: If acme.sh cannot register immediately (e.g. network issue), the configuration still stores the CA/email; re-run the command when the issue is resolved.

### 6.4 `fritzcert list`

- **Syntax**: `fritzcert list`
- **Output**:
  ```
  - home: fritzbox.home.example.com (dns_gd)
  - office: fritzbox.office.example.com (dns_cf)
  ```
- **Exit codes**: `0` on success; `0` with message `No Fritz!Box configured.` when empty configuration.

### 6.5 `fritzcert add-box`

- **Syntax** (abridged):
  ```
  sudo fritzcert add-box \
    --name NAME \
    --domain DOMAIN \
    --dns-plugin PLUGIN \
    [--dns-cred KEY=VALUE ... | --dns-cred-file PATH] \
    --fritz-url URL \
    --fritz-user USER \
    [--fritz-pass VALUE | --fritz-pass-file PATH] \
    [--fritz-ca-file PATH] \
    [--allow-insecure-tls] \
    [--key-type KEYTYPE]
  ```
- **Secrets**: `VALUE` may be `?`, `@env:VAR`, or a literal.
- **Idempotency**: Re-running with the same `--name` replaces previous settings.
- **Example (combining interactive prompt and env variable)**:
  ```
  export CF_TOKEN=cf_xxxxx
  sudo --preserve-env=CF_TOKEN fritzcert add-box \
    --name office \
    --domain fritzbox.office.example.com \
    --dns-plugin dns_cf \
    --dns-cred CF_Token=@env:CF_TOKEN \
    --fritz-url https://fritzbox.office.example.com \
    --fritz-user admin \
    --fritz-pass ? \
    --key-type ec-256
  ```
- **Result**: Updates `/etc/fritzcert/config.yaml`, prints `Box 'office' added successfully.`
- **Validation**: Ensures required fields and secure permissions on secret files.

### 6.6 `fritzcert remove-box`

- **Syntax**: `sudo fritzcert remove-box --name NAME`
- **Output**:
  ```
  Box 'office' removed.
  ```
- **Error** (non-existent name):
  ```
  No box found with name 'office'.
  ```

### 6.7 `fritzcert issue`

- **Syntax**: `sudo fritzcert issue [--name NAME]`
- **Purpose**: Executes `acme.sh --issue` with the configured DNS plugin and credentials. Without `--name`, all boxes are processed.
- **Output**: Streams progress to stdout; logs commands executed (`[acme.sh] exec ...`). On success prints `[OK] Certificate written to /var/lib/fritzcert/<box>/fritzbox.pem`.
- **Error handling**: Non-zero acme.sh exit codes produce a detailed error containing stdout and stderr from acme.sh.

### 6.8 `fritzcert deploy`

- **Syntax**: `sudo fritzcert deploy [--name NAME]`
- **Behavior**:
  1. Obtains SID using `login_sid.lua` with challenge-response.
  2. Uploads via `system/certificate_upload.lua`.
  3. Always attempts fallback `cgi-bin/firmwarecfg`.
- **Output**:
  ```
  Upload (method 1) certificate_upload.lua ...
  Upload (method 2) firmwarecfg ...
  Deploy completed
  ```
- **TLS options**: Uses `ca_cert` or `allow_insecure` from configuration.

### 6.9 `fritzcert renew`

- **Syntax**: `sudo fritzcert renew`
- **Purpose**: Calls `acme.sh --cron --home <ACME_HOME>` to renew due certificates. Suitable for periodic automation.
- **Output**:
  ```
  [INFO] Running acme.sh --cron ...
  [OK] Renewal pass completed.
  ```

### 6.10 `fritzcert status`

- **Syntax**: `fritzcert status`
- **Output**:
  ```
  [home] Certificate: /var/lib/fritzcert/home/fritzbox.pem
    Key: /var/lib/fritzcert/home/fritzbox.key
    Expires: May 13 21:45:20 2025 GMT
  ```
- Reports `No certificate found.` if the PEM is missing.

### 6.11 `fritzcert install-systemd`

- **Syntax**: `sudo fritzcert install-systemd`
- **Effect**: Writes `/etc/systemd/system/fritzcert.service` and `.timer`, reloads systemd, enables the timer immediately.
- **To inspect**: `systemctl status fritzcert.timer` and `journalctl -u fritzcert.service`.
- **Removal**: `sudo fritzcert install-systemd` is idempotent; to remove use `sudo make uninstall-systemd` (see §7).

### 6.12 `fritzcert install-completion`

- **Syntax**:
  ```
  fritzcert install-completion --shell {bash,zsh} [--dest PATH]
  ```
- **Notes**:
  - Installs the completion script to the default location for the specified shell (root vs non-root paths differ).
  - Appends a sourcing snippet to `~/.bashrc` or `~/.zshrc` when running as a non-root user.
  - Run as root to install system-wide completions; re-run as the target user to enable completion in their profile.

---

## 7. Makefile Targets

| Target | Description |
|--------|-------------|
| `make install` | Full installation via pipx, directory setup, completion install, systemd automation |
| `make install-venv` | Install in `/opt/fritzcert-cli-venv/` virtual environment |
| `make uninstall` | Remove pipx/venv installation (keeps configuration/state) |
| `make update` | `git pull` + pipx reinstall (or venv refresh) |
| `make build` | Build wheel(s) in `dist/` |
| `make dirs` | Only create directories (`/etc`, `/var/lib`, `/var/log`) with secure permissions |
| `make install-systemd` | Install/enable systemd units (same as CLI command) |
| `make uninstall-systemd` | Disable and remove the systemd units |
| `make clean` | Remove build artefacts (`dist`, `build`, `__pycache__`, etc.) |

---

## 8. Automation Strategies

### 8.1 Systemd (recommended)

```
sudo fritzcert install-systemd
systemctl status fritzcert.timer
```

- Runs daily with a randomized delay (default `OnCalendar=daily`, `RandomizedDelaySec=1800`).
- Unit files are located in `/etc/systemd/system/`.
- Logs accessible via `journalctl -u fritzcert.service`.

Disable/remove automation:

```
sudo make uninstall-systemd
```

### 8.2 Cron (fallback when systemd is unavailable)

```
sudo crontab -e
```

Add a line such as:

```
0 3 * * * /root/.acme.sh/acme.sh --cron --home "/root/.acme.sh" > /dev/null; /usr/local/bin/fritzcert deploy >> /var/log/fritzcert/cron.log 2>&1
```

Adjust paths as required for non-root installations.

---

## 9. Logs & Diagnostics

| Location | Contents |
|----------|----------|
| `/var/log/fritzcert/fritzcert.log` | High-level log of command executions |
| `journalctl -u fritzcert.service` | Detailed output from automated renew/deploy runs |
| `/root/.acme.sh/acme.sh.log` | acme.sh cron log (when cron is used) |

**Log rotation**: Managed externally (e.g. `logrotate`). Add `/var/log/fritzcert/fritzcert.log` to your rotation policy if needed.

### Useful troubleshooting commands

```
# Check the latest backup of the configuration
sudo ls -ltr /etc/fritzcert/backups/

# Inspect the TLS certificate presented by the FRITZ!Box
echo | openssl s_client -connect fritzbox.example.com:443 -servername fritzbox.example.com 2>/dev/null | openssl x509 -noout -issuer -subject -enddate

# Manually test the FRITZ!Box login endpoint
curl -s https://fritzbox.example.com/login_sid.lua
```

---

## 10. Security Best Practices

1. **Principle of least privilege**: run `fritzcert` with the minimum required privileges. Interactive commands typically require root only because the configuration and state directories are root-owned.
2. **Secrets off the command line**: prefer `?` prompts or `@env:` descriptors. Literal secrets remain visible in process listings.
3. **CA pinning**: specify `--fritz-ca-file` for each box to prevent man-in-the-middle attacks when communicating with the FRITZ!Box.
4. **Avoid `--allow-insecure-tls`**: enabling it suppresses certificate verification; use only for temporary troubleshooting.
5. **Review backups**: `/etc/fritzcert/backups/` inherits `chmod 700`. Keep it on secure storage and include in your system backups.
6. **Audit the FRITZ!Box**: ensure the administrative password is unique and strong; restrict WAN access to the FRITZ!Box management interface.
7. **Monitor automation**: configure alerting (e.g. via `systemd` OnFailure directives) to be notified if renewals fail.

---

## 11. Maintenance & Updates

### 11.1 Updating fritzcert-cli

```
git pull
make update
```

`make update` reinstalls the CLI via pipx (or refreshes the `/opt` venv) after pulling the latest sources.

### 11.2 Upgrading acme.sh version

If you need a newer acme.sh release:

1. Update `ACME_VERSION` and `ACME_ARCHIVE_SHA256` in `src/fritzcert_cli/acme.py`.
2. Reinstall fritzcert-cli (`make update`).
3. Re-run `fritzcert issue` to ensure the new version operates correctly.

### 11.3 Uninstalling cleanly

```
sudo make uninstall       # removes CLI
sudo make uninstall-systemd
sudo rm -rf /etc/fritzcert /var/lib/fritzcert /var/log/fritzcert
sudo rm -rf /root/.acme.sh
```

Delete configuration/state only when you are certain they are no longer needed.

---

## 12. Troubleshooting Guide

| Symptom | Possible cause | Resolution |
|---------|----------------|------------|
| `Box 'name' not found.` | Typo in `--name` or box not configured | Run `fritzcert list` to confirm names |
| `acme.sh --issue failed ... EAB required` | ZeroSSL or CA requiring EAB credentials | Register account with appropriate EAB values, verify `config.yaml` |
| `firmwarecfg upload failed` | FRITZ!Box rejecting the certificate | Verify CA pinning, ensure the FRITZ!Box trusts the chain, retry after reboot |
| `Permission denied writing completion script` | Destination requires elevated privileges | Re-run with `sudo` or specify a path under your home directory |
| acme.sh download failure | Network restrictions or outdated hash/version | Check connectivity, update SHA256 in `acme.py` if the upstream release changed |
| Certificate not activated | FRITZ!Box still serves old certificate | Access via the hostname (not IP), trigger FRITZ!Box reboot if necessary |
| `Fritz!Box authentication failed.` | Incorrect credentials or IP restrictions | Verify username/password, ensure FRITZ!Box allows login from host |

Additional tips:

- Use `openssl x509 -in /var/lib/fritzcert/<box>/fritzbox.pem -text -noout` to inspect the certificate before deployment.
- If `fritzcert issue` fails on DNS validation, confirm that the DNS provider credentials have sufficient permissions and that propagation time is respected.

---

## 13. Frequently Asked Questions

**Q1**: *Can I manage multiple FRITZ!Box devices with different DNS providers?*  
**A**: Yes. Each `boxes` entry specifies its own `dns_provider` and credentials. `fritzcert issue` and `deploy` iterate over all boxes unless restricted via `--name`.

**Q2**: *Can I use HTTP-01 challenges instead of DNS-01?*  
**A**: Not in the current release. `fritzcert` relies solely on DNS-01 to avoid exposing the FRITZ!Box’s HTTP interface externally.

**Q3**: *Where is the FRITZ!Box password stored?*  
**A**: Inside `/etc/fritzcert/config.yaml`, written with `chmod 600`. Protect this file accordingly and monitor `/etc/fritzcert/backups/`.

**Q4**: *How do I stage certificates for testing?*  
**A**: Set the account CA to Let’s Encrypt’s staging environment by editing `config.yaml` and pointing `acme.sh` to the staging server (`--server letsencrypt_test` in `acme.py` if desired).

**Q5**: *Does the CLI support IPv6-only environments?*  
**A**: Yes, as long as the FRITZ!Box and DNS provider are reachable over IPv6.

---

## 14. Contributing & Support

- Repository: https://github.com/jmbriccola/fritzcert
- Issues: https://github.com/jmbriccola/fritzcert/issues
- Email: jmbriccola@gmail.com

When submitting issues, include:

1. Output of `fritzcert --version`
2. Relevant command output (redact credentials)
3. `journalctl -u fritzcert.service` excerpts, if automation is involved
4. FRITZ!Box model and FRITZ!OS version

Pull requests are welcome. Please adhere to PEP 8, include unit/integration tests where feasible, and document new behavior in this README.

---

## 15. Licensing

MIT License © 2025 Jacopo Maria Briccola

The project started from an AI-assisted codebase and has been hardened for production usage; nevertheless, audit the code in your environment, especially when interacting with critical infrastructure.
