SYSTEMD_USER_DIR ?= $(HOME)/.config/systemd/user
SYSTEMD_GLOBAL_USER_DIR ?= /etc/systemd/user

# pyright is commonly installed by an editor package manager rather than onto
# PATH, so fall back to the Mason location before giving up.
PYRIGHT ?= $(shell command -v pyright 2>/dev/null || echo $(HOME)/.local/share/nvim/mason/bin/pyright)

.PHONY: install uninstall reinstall dev test typecheck

install:
	pip install --break-system-packages .
	@BIN=$$(command -v da || echo /usr/local/bin/da); \
	if [ "$$(id -u)" = "0" ]; then \
		DEST=$(SYSTEMD_GLOBAL_USER_DIR)/da.service; \
	else \
		mkdir -p $(SYSTEMD_USER_DIR); \
		DEST=$(SYSTEMD_USER_DIR)/da.service; \
	fi; \
	sed "s|^ExecStart=.*|ExecStart=$$BIN|" systemd/da.service > $$DEST; \
	chmod 644 $$DEST; \
	echo "Installed unit to $$DEST (ExecStart=$$BIN)"
	@echo "Start da either from dwm's autostart (nohup da &)"
	@echo "or via 'systemctl --user enable --now da' (needs DISPLAY imported:"
	@echo "systemctl --user import-environment DISPLAY). Pick ONE method."

uninstall:
	pip uninstall -y da --break-system-packages
	rm -f $(SYSTEMD_USER_DIR)/da.service
	@if [ "$$(id -u)" = "0" ]; then rm -f $(SYSTEMD_GLOBAL_USER_DIR)/da.service; fi
	@echo "Uninstalled."

reinstall: uninstall install

# The stub package needs PYGOBJECT_STUB_CONFIG at install time to select GTK3,
# and the <2.17 pin keeps it compatible with the distro's PyGObject 3.48
# (2.17 requires >=3.55 and would try to build PyGObject from source).
dev:
	pip install --break-system-packages -e '.[dev]'
	PYGOBJECT_STUB_CONFIG=Gtk3,Gdk3 pip install --break-system-packages \
		--no-cache-dir 'pygobject-stubs<2.17'

test:
	PYTHONPATH=src python3 -m pytest tests/ -q

# Asserts a nonzero file count: pyright silently analyses nothing if the
# include paths do not resolve, which otherwise reads as a clean run.
typecheck:
	@test -x "$(PYRIGHT)" || { echo "pyright not found (tried: $(PYRIGHT))"; exit 1; }
	@"$(PYRIGHT)" --project . --outputjson > /tmp/da-pyright.json || true
	@python3 -c "import json, sys; \
s = json.load(open('/tmp/da-pyright.json'))['summary']; \
print('pyright: %d files, %d errors, %d warnings' % (s['filesAnalyzed'], s['errorCount'], s['warningCount'])); \
sys.exit(1) if s['filesAnalyzed'] == 0 or s['errorCount'] else None"
