SYSTEMD_SYSTEM_DIR ?= /etc/systemd/system

.PHONY: install uninstall reinstall

install:
	pip install --break-system-packages .
	install -m 644 systemd/displayd-watcher.service $(SYSTEMD_SYSTEM_DIR)/displayd-watcher.service
	systemctl daemon-reload
	systemctl enable --now displayd-watcher
	@echo "Installed and started."

uninstall:
	-systemctl disable --now displayd-watcher 2>/dev/null
	pip uninstall -y displayd --break-system-packages
	rm -f $(SYSTEMD_SYSTEM_DIR)/displayd-watcher.service
	systemctl daemon-reload
	@echo "Uninstalled."

reinstall: uninstall install
