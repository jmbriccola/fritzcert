# ==========================================================
# Makefile per fritzcert-cli (install auto con pipx o fallback venv)
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

.PHONY: help install uninstall build update package clean dirs install-venv

help:
	@echo ""
	@echo "Comandi disponibili:"
	@echo "  make install        -> installa la CLI con pipx (auto-installa pipx se manca)"
	@echo "  make uninstall      -> disinstalla la CLI da pipx (o rimuove venv)"
	@echo "  make build          -> crea il wheel (.whl)"
	@echo "  make update         -> reinstalla/aggiorna via pipx"
	@echo "  make dirs           -> crea dir di sistema (/etc, /var/lib, /var/log)"
	@echo "  make install-venv   -> alternativa: venv in /opt + symlink in /usr/local/bin"
	@echo "  make clean          -> pulizia build/cache"
	@echo ""

dirs:
	@sudo mkdir -p $(CONF_DIR) $(CONF_DIR)/backups $(STATE_DIR) $(LOG_DIR)
	@sudo chmod 755 $(CONF_DIR) $(CONF_DIR)/backups $(STATE_DIR) $(LOG_DIR)
	@echo "✅ Directory di sistema pronte."

install: dirs
	@set -e; \
	echo "▶ Verifica pipx..."; \
	if ! command -v $(PIPX) >/dev/null 2>&1 && [ ! -x "$(PIPX_BIN)" ]; then \
		echo "▶ Installo pipx (richiede sudo)..."; \
		sudo apt update && sudo apt install -y pipx python3-venv; \
	fi; \
	echo "▶ Build wheel (isolato) ..."; \
	$(PIPX) run build --wheel; \
	WHEEL=$$(ls -1 $(BUILD_DIR)/*.whl | tail -n1); \
	if [ -z "$$WHEEL" ]; then echo "❌ Nessuna wheel trovata in $(BUILD_DIR)"; exit 1; fi; \
	PIPX_CMD="$$(command -v $(PIPX) 2>/dev/null || echo $(PIPX_BIN))"; \
	if [ ! -x "$$PIPX_CMD" ]; then \
		echo "⚠️  pipx non disponibile, fallback venv in /opt..."; \
		$(MAKE) install-venv; \
	else \
		echo "▶ Installazione tramite pipx della wheel $$WHEEL ..."; \
		"$$PIPX_CMD" install --force "$$WHEEL"; \
		if [ -x "$(HOME)/.local/bin/fritzcert" ]; then \
			echo "▶ Creo symlink globale in /usr/local/bin ..."; \
			sudo ln -sf $(HOME)/.local/bin/fritzcert /usr/local/bin/fritzcert; \
		fi; \
		echo "✅ Installazione completata via pipx. Se 'fritzcert' non è nel PATH, esegui: $$PIPX_CMD ensurepath e riapri la shell."; \
	fi

uninstall:
	@echo "▶ Disinstallazione..."
	@if command -v $(PIPX) >/dev/null 2>&1 || [ -x "$(PIPX_BIN)" ]; then \
		PIPX_CMD="$$(command -v $(PIPX) 2>/dev/null || echo $(PIPX_BIN))"; \
		"$$PIPX_CMD" uninstall $(PKG_NAME) || true; \
	fi
	@# rimuovi eventuale venv in /opt usato dal fallback
	@sudo rm -rf /opt/$(PKG_NAME)-venv /usr/local/bin/fritzcert || true
	@echo "✅ Disinstallato."

build:
	@echo "▶ Build wheel (isolato) ..."
	@$(PIPX) run build --wheel
	@ls -lh $(BUILD_DIR)

update:
	@echo "▶ Aggiornamento..."
	@PIPX_CMD="$$(command -v $(PIPX) 2>/dev/null || echo $(PIPX_BIN))"; \
	if [ -x "$$PIPX_CMD" ]; then \
		"$$PIPX_CMD" reinstall $(PKG_NAME) . || "$$PIPX_CMD" install --force .; \
		echo "✅ Aggiornamento completato (pipx)."; \
	else \
		echo "⚠️  pipx non disponibile, aggiorno venv in /opt..."; \
		$(MAKE) install-venv; \
	fi

# Alternativa senza pipx: venv di sistema in /opt + symlink CLI
install-venv: dirs
	@echo "▶ Installazione in venv /opt/$(PKG_NAME)-venv ..."
	@sudo /bin/bash -lc '\
	  set -e; \
	  apt-get update && apt-get install -y python3-venv >/dev/null; \
	  if [ ! -d /opt/$(PKG_NAME)-venv ]; then python3 -m venv /opt/$(PKG_NAME)-venv; fi; \
	  /opt/$(PKG_NAME)-venv/bin/pip install --upgrade pip; \
	  /opt/$(PKG_NAME)-venv/bin/pip install --upgrade .; \
	  ln -sf /opt/$(PKG_NAME)-venv/bin/fritzcert /usr/local/bin/fritzcert; \
	'
	@echo "✅ Installazione in venv completata."

clean:
	rm -rf $(BUILD_DIR) build *.egg-info __pycache__ */__pycache__
	@echo "🧹 Pulizia completata."

SYSTEMD_DIR   = /etc/systemd/system
SERVICE_FILE  = $(SYSTEMD_DIR)/fritzcert.service
TIMER_FILE    = $(SYSTEMD_DIR)/fritzcert.timer

.PHONY: install-systemd uninstall-systemd

install-systemd:
	@echo "▶ Installo unità systemd..."
	@echo "[Unit]\nDescription=Renew Let's Encrypt and deploy to FRITZ!Box (fritzcert)\nWants=network-online.target\nAfter=network-online.target\n\n[Service]\nType=oneshot\nUser=root\nExecStart=/usr/local/bin/fritzcert renew\nExecStartPost=/usr/local/bin/fritzcert deploy\n" | sudo tee $(SERVICE_FILE) >/dev/null
	@echo "[Unit]\nDescription=Daily fritzcert renew + deploy\n\n[Timer]\nOnCalendar=daily\nRandomizedDelaySec=1800\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n" | sudo tee $(TIMER_FILE) >/dev/null
	@sudo systemctl daemon-reload
	@sudo systemctl enable --now fritzcert.timer
	@echo "✅ Systemd timer attivo: fritzcert.timer"
	@echo "   Controllo: systemctl list-timers | grep fritzcert"
	@echo "   Log:       journalctl -u fritzcert.service -n 200 --no-pager"

uninstall-systemd:
	@echo "▶ Rimuovo unità systemd..."
	@sudo systemctl disable --now fritzcert.timer || true
	@sudo rm -f $(SERVICE_FILE) $(TIMER_FILE)
	@sudo systemctl daemon-reload
	@echo "✅ Systemd rimosso."