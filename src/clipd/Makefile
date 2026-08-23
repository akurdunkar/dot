SYSTEMD_USER_DIR ?= $(HOME)/.config/systemd/user
SYSTEMD_GLOBAL_USER_DIR ?= /etc/systemd/user

# XDG desktop integration (Ubuntu/GNOME and friends). Root installs go to
# the system-wide locations, user installs stay under $HOME.
ifeq ($(shell id -u),0)
APPS_DIR ?= /usr/local/share/applications
ICON_DIR ?= /usr/local/share/icons/hicolor/scalable/apps
AUTOSTART_DIR ?= /etc/xdg/autostart
else
APPS_DIR ?= $(HOME)/.local/share/applications
ICON_DIR ?= $(HOME)/.local/share/icons/hicolor/scalable/apps
AUTOSTART_DIR ?= $(HOME)/.config/autostart
endif

# pyright is commonly installed by an editor package manager rather than onto
# PATH, so fall back to the Mason location before giving up.
PYRIGHT ?= $(shell command -v pyright 2>/dev/null || echo $(HOME)/.local/share/nvim/mason/bin/pyright)

.PHONY: install uninstall reinstall autostart dev test typecheck smoke

install:
	pip install --break-system-packages .
	@BIN=$$(command -v clipd || echo /usr/local/bin/clipd); \
	if [ "$$(id -u)" = "0" ]; then \
		DEST=$(SYSTEMD_GLOBAL_USER_DIR)/clipd.service; \
	else \
		mkdir -p $(SYSTEMD_USER_DIR); \
		DEST=$(SYSTEMD_USER_DIR)/clipd.service; \
	fi; \
	sed "s|^ExecStart=.*|ExecStart=$$BIN|" systemd/clipd.service > $$DEST; \
	chmod 644 $$DEST; \
	echo "Installed unit to $$DEST (ExecStart=$$BIN)"
	@BIN=$$(command -v clipd || echo /usr/local/bin/clipd); \
	mkdir -p $(APPS_DIR) $(ICON_DIR); \
	sed -e "s|^Exec=env GDK_BACKEND=x11 clipd|Exec=env GDK_BACKEND=x11 $$BIN|" \
	    -e "s|^TryExec=.*|TryExec=$$BIN|" \
	    data/org.clipd.Clipd.desktop > $(APPS_DIR)/org.clipd.Clipd.desktop; \
	install -m 644 data/org.clipd.Clipd.svg $(ICON_DIR)/org.clipd.Clipd.svg; \
	update-desktop-database -q $(APPS_DIR) 2>/dev/null || true; \
	gtk-update-icon-cache -q $(dir $(dir $(dir $(ICON_DIR)))) 2>/dev/null || true; \
	echo "Installed desktop entry and icon"
	@echo "Start clipd either from dwm's autostart (nohup clipd &),"
	@echo "via 'systemctl --user enable --now clipd' (needs DISPLAY imported:"
	@echo "systemctl --user import-environment DISPLAY DBUS_SESSION_BUS_ADDRESS),"
	@echo "or on GNOME/KDE/XFCE via 'make autostart'. Pick ONE method."

# XDG autostart (the standard login-start mechanism on GNOME/KDE/XFCE).
# dwm ignores these files, so it never conflicts with the dwm autostart.
autostart:
	@BIN=$$(command -v clipd || echo /usr/local/bin/clipd); \
	mkdir -p $(AUTOSTART_DIR); \
	sed -e "s|^Exec=env GDK_BACKEND=x11 clipd|Exec=env GDK_BACKEND=x11 $$BIN|" \
	    -e "s|^TryExec=.*|TryExec=$$BIN|" \
	    data/org.clipd.Clipd-autostart.desktop > $(AUTOSTART_DIR)/org.clipd.Clipd-autostart.desktop; \
	echo "Installed autostart entry to $(AUTOSTART_DIR)"

uninstall:
	pip uninstall -y clipd --break-system-packages
	rm -f $(SYSTEMD_USER_DIR)/clipd.service
	rm -f $(APPS_DIR)/org.clipd.Clipd.desktop $(ICON_DIR)/org.clipd.Clipd.svg
	rm -f $(AUTOSTART_DIR)/org.clipd.Clipd-autostart.desktop
	@if [ "$$(id -u)" = "0" ]; then rm -f $(SYSTEMD_GLOBAL_USER_DIR)/clipd.service; fi
	@update-desktop-database -q $(APPS_DIR) 2>/dev/null || true
	@echo "Uninstalled."

reinstall: uninstall install

# The stub package needs PYGOBJECT_STUB_CONFIG at install time to select GTK4,
# and the <2.17 pin keeps it compatible with the distro's PyGObject 3.48
# (2.17 requires >=3.55 and would try to build PyGObject from source).
dev:
	pip install --break-system-packages -e '.[dev]'
	PYGOBJECT_STUB_CONFIG=Gtk4,Gdk4 pip install --break-system-packages \
		--no-cache-dir 'pygobject-stubs<2.17'

test:
	PYTHONPATH=src python3 -m pytest tests/ -q

# End-to-end run inside Xvfb with an isolated D-Bus: capture from xclip,
# exercise the CLI, take screenshots. See smoke/run.sh output for artifacts.
smoke:
	bash smoke/run.sh

# Asserts a nonzero file count: pyright silently analyses nothing if the
# include paths do not resolve, which otherwise reads as a clean run.
typecheck:
	@test -x "$(PYRIGHT)" || { echo "pyright not found (tried: $(PYRIGHT))"; exit 1; }
	@"$(PYRIGHT)" --project . --outputjson > /tmp/clipd-pyright.json || true
	@python3 -c "import json, sys; \
s = json.load(open('/tmp/clipd-pyright.json'))['summary']; \
print('pyright: %d files, %d errors, %d warnings' % (s['filesAnalyzed'], s['errorCount'], s['warningCount'])); \
sys.exit(1) if s['filesAnalyzed'] == 0 or s['errorCount'] else None"
