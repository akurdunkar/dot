SYSTEMD_USER_DIR ?= $(HOME)/.config/systemd/user
SYSTEMD_GLOBAL_USER_DIR ?= /etc/systemd/user

.PHONY: install uninstall reinstall migrate test

install:
	pip install --break-system-packages .
	@BIN=$$(command -v displayd || echo /usr/local/bin/displayd); \
	if [ "$$(id -u)" = "0" ]; then \
		DEST=$(SYSTEMD_GLOBAL_USER_DIR)/displayd.service; \
	else \
		mkdir -p $(SYSTEMD_USER_DIR); \
		DEST=$(SYSTEMD_USER_DIR)/displayd.service; \
	fi; \
	sed "s|^ExecStart=.*|ExecStart=$$BIN|" systemd/displayd.service > $$DEST; \
	chmod 644 $$DEST; \
	echo "Installed unit to $$DEST (ExecStart=$$BIN)"
	@echo "Start displayd either from dwm autostart.sh (nohup displayd &)"
	@echo "or via 'systemctl --user enable --now displayd' (needs DISPLAY imported:"
	@echo "systemctl --user import-environment DISPLAY). Pick ONE method."

uninstall:
	pip uninstall -y displayd --break-system-packages
	rm -f $(SYSTEMD_USER_DIR)/displayd.service
	@if [ "$$(id -u)" = "0" ]; then rm -f $(SYSTEMD_GLOBAL_USER_DIR)/displayd.service; fi
	@echo "Uninstalled."

migrate:
	@if [ "$$(id -u)" != "0" ]; then echo "migrate needs root (sudo make migrate)"; fi
	-systemctl disable --now displayd-watcher 2>/dev/null || true
	rm -f /etc/systemd/system/displayd-watcher.service
	systemctl daemon-reload
	-pkill -x displayd-agent || true
	@echo "done"

reinstall: uninstall install

test:
	PYTHONPATH=src python3 -m pytest tests/ -q
