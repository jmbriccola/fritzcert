# ==========================================================
# Makefile for fritzcert-cli (auto install via pipx or fallback venv)
# ==========================================================

PYTHON       ?= python3
PIP          ?= $(PYTHON) -m pip
PIPX         ?= pipx
PKG_NAME     = fritzcert-cli
VERSION      = 0.1.0
BUILD_DIR    = dist
CONF_DIR     = /etc/fritzcert
STATE_DIR    = /var/lib/fritzcert
LOG_DIR      = /var/log/fritzcert
PIPX_BIN     := $(HOME)/.local/bin/pipx

.PHONY: help install uninstall build update package clean dirs install-venv install-systemd uninstall-systemd

help:
	@echo ""
	@echo "Available commands:"
	@echo "  make install          -> install CLI with pipx (auto-installs pipx) + ensure acme.sh + enable systemd timer"
	@echo "  make uninstall        -> uninstall CLI and remove /opt venv symlink"
	@echo "  make build            -> build the wheel (.whl)"
	@echo "  make update           -> git pull + pipx reinstall (or venv reinstall)"
	@echo "  make dirs             -> create system dirs (/etc, /var/lib, /var/log)"
	@echo "  make install-venv     -> alternative: venv in /opt + symlink in /usr/local/bin"
	@echo "  make install-systemd  -> install/enable systemd renew+deploy timer"
	@echo "  make uninstall-systemd-> remove systemd timer and service"
	@echo "  make clean            -> clean build artifacts"
	@echo ""

dirs:
	@sudo mkdir -p $(CONF_DIR) $(CONF_DIR)/backups $(STATE_DIR) $(LOG_DIR)
	@sudo chmod 700 $(CONF_DIR) $(CONF_DIR)/backups $(STATE_DIR) $(LOG_DIR)
	@echo "[OK] System directories are ready."

install: dirs
	@set -e; \
	echo "[INFO] fritzcert will download and verify acme.sh automatically on first use."; \
	echo "[INFO] Checking pipx..."; \
	if ! command -v $(PIPX) >/dev/null 2>&1 && [ ! -x "$(PIPX_BIN)" ]; then \
		echo "[INFO] Installing pipx (requires sudo)..."; \
		sudo apt update && sudo apt install -y pipx python3-venv; \
	fi; \
	echo "[INFO] Building wheel (isolated) ..."; \
	$(PIPX) run build --wheel; \
	WHEEL=$$(ls -1 $(BUILD_DIR)/*.whl | tail -n1); \
	if [ -z "$$WHEEL" ]; then echo "[ERROR] No wheel found in $(BUILD_DIR)"; exit 1; fi; \
	PIPX_CMD="$$(command -v $(PIPX) 2>/dev/null || echo $(PIPX_BIN))"; \
	if [ ! -x "$$PIPX_CMD" ]; then \
		echo "[WARN] pipx not available, falling back to venv in /opt..."; \
		$(MAKE) install-venv; \
	else \
		echo "[INFO] Installing wheel via pipx: $$WHEEL ..."; \
		"$$PIPX_CMD" install --force "$$WHEEL"; \
		if [ -x "$(HOME)/.local/bin/fritzcert" ]; then \
			echo "[INFO] Creating global symlink in /usr/local/bin ..."; \
			sudo ln -sf $(HOME)/.local/bin/fritzcert /usr/local/bin/fritzcert; \
		fi; \
		$(MAKE) install-systemd; \
		if ! sudo fritzcert install-completion --shell bash >/dev/null 2>&1; then \
			echo "[WARN] Could not install bash completion automatically."; \
		fi; \
		if command -v zsh >/dev/null 2>&1; then \
			sudo fritzcert install-completion --shell zsh >/dev/null 2>&1 || echo "[WARN] Could not install zsh completion automatically."; \
		fi; \
		if [ -n "$$SUDO_USER" ]; then \
			if ! sudo -u "$$SUDO_USER" fritzcert install-completion --shell bash >/dev/null 2>&1; then \
				echo "[WARN] Could not configure bash completion for $$SUDO_USER automatically."; \
			fi; \
			if command -v zsh >/dev/null 2>&1; then \
				sudo -u "$$SUDO_USER" fritzcert install-completion --shell zsh >/dev/null 2>&1 || echo "[WARN] Could not configure zsh completion for $$SUDO_USER automatically."; \
			fi; \
		fi; \
		echo "[OK] Installation completed via pipx. If 'fritzcert' is not in PATH, run: $$PIPX_CMD ensurepath and reopen the shell."; \
	fi

uninstall:
	@echo "[INFO] Uninstalling..."
	@if command -v $(PIPX) >/dev/null 2>&1 || [ -x "$(PIPX_BIN)" ]; then \
		PIPX_CMD="$$(command -v $(PIPX) 2>/dev/null || echo $(PIPX_BIN))"; \
		"$$PIPX_CMD" uninstall $(PKG_NAME) || true; \
	fi
	@# remove optional fallback venv and symlink
	@sudo rm -rf /opt/$(PKG_NAME)-venv /usr/local/bin/fritzcert || true
	@echo "[OK] Uninstalled."

build:
	@echo "[INFO] Building wheel (isolated) ..."
	@$(PIPX) run build --wheel
	@ls -lh $(BUILD_DIR)

update:
	@echo "[INFO] Updating sources ..."
	@git pull
	@PIPX_CMD="$$(command -v $(PIPX) 2>/dev/null || echo $(PIPX_BIN))"; \
	if [ -x "$$PIPX_CMD" ]; then \
		"$$PIPX_CMD" reinstall $(PKG_NAME) . || "$$PIPX_CMD" install --force .; \
		echo "[OK] Update completed (pipx)."; \
	else \
		echo "[WARN] pipx not available, updating venv in /opt..."; \
		$(MAKE) install-venv; \
	fi

# Alternative without pipx: system venv in /opt + CLI symlink
install-venv: dirs
	@echo "[INFO] Installing in venv /opt/$(PKG_NAME)-venv ..."
	@sudo /bin/bash -lc '\
	  set -e; \
	  apt-get update && apt-get install -y python3-venv >/dev/null; \
	  if [ ! -d /opt/$(PKG_NAME)-venv ]; then python3 -m venv /opt/$(PKG_NAME)-venv; fi; \
	  /opt/$(PKG_NAME)-venv/bin/pip install --upgrade pip; \
	  /opt/$(PKG_NAME)-venv/bin/pip install --upgrade .; \
	  ln -sf /opt/$(PKG_NAME)-venv/bin/fritzcert /usr/local/bin/fritzcert; \
	  if ! fritzcert install-completion --shell bash >/dev/null 2>&1; then \
	    echo "[WARN] Could not install bash completion automatically."; \
	  fi; \
	  if command -v zsh >/dev/null 2>&1; then \
	    fritzcert install-completion --shell zsh >/dev/null 2>&1 || echo "[WARN] Could not install zsh completion automatically."; \
	  fi; \
	  if [ -n "$$SUDO_USER" ]; then \
	    if ! sudo -u "$$SUDO_USER" fritzcert install-completion --shell bash >/dev/null 2>&1; then \
	      echo "[WARN] Could not configure bash completion for $$SUDO_USER automatically."; \
	    fi; \
	    if command -v zsh >/dev/null 2>&1; then \
	      sudo -u "$$SUDO_USER" fritzcert install-completion --shell zsh >/dev/null 2>&1 || echo "[WARN] Could not configure zsh completion for $$SUDO_USER automatically."; \
	    fi; \
	  fi; \
	'
	@echo "[OK] venv installation completed."

SYSTEMD_DIR   = /etc/systemd/system
SERVICE_FILE  = $(SYSTEMD_DIR)/fritzcert.service
TIMER_FILE    = $(SYSTEMD_DIR)/fritzcert.timer

install-systemd:
	@echo "[INFO] Installing systemd units..."
	@echo "[Unit]\nDescription=Renew Let's Encrypt and deploy to FRITZ!Box (fritzcert)\nWants=network-online.target\nAfter=network-online.target\n\n[Service]\nType=oneshot\nUser=root\nExecStart=/usr/local/bin/fritzcert renew\nExecStartPost=/usr/local/bin/fritzcert deploy\n" | sudo tee $(SERVICE_FILE) >/dev/null
	@echo "[Unit]\nDescription=Daily fritzcert renew + deploy\n\n[Timer]\nOnCalendar=daily\nRandomizedDelaySec=1800\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n" | sudo tee $(TIMER_FILE) >/dev/null
	@sudo systemctl daemon-reload
	@sudo systemctl enable --now fritzcert.timer
	@echo "[OK] Systemd timer active: fritzcert.timer"

uninstall-systemd:
	@echo "[INFO] Removing systemd units..."
	@sudo systemctl disable --now fritzcert.timer || true
	@sudo rm -f $(SERVICE_FILE) $(TIMER_FILE)
	@sudo systemctl daemon-reload
	@echo "[OK] Systemd removed."


clean:
	rm -rf $(BUILD_DIR) build src/*.egg-info __pycache__ */__pycache__
	@echo "[OK] Clean completed."
