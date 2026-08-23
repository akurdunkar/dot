"""Single-instance application: daemon, GUI and CLI in one binary.

GApplication uniqueness (D-Bus) makes every later `clipd <cmd>` invocation
a remote call into the running daemon: `do_command_line` executes in the
primary instance and prints back over the wire to the caller's terminal.
So there is exactly one process owning the database, the clipboard watcher,
the popup and the tray — CLI clients are free.
"""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from clipd import APP_ID, __version__, log
from clipd.clipboard import ClipboardService
from clipd.config import Config, db_path
from clipd.store import KIND_IMAGE, Entry, Store
from clipd.ui.menu import TrayMenu
from clipd.ui.settings import SettingsDialog
from clipd.ui.window import ClipWindow
from clipd.x11.paste import Paster
from clipd.x11.tray import TrayIcon
from clipd.x11.wm import WindowDresser

_LOG = log.get(__name__)
_PASTE_DELAY_MS = 160

_HELP = """\
clipd — clipboard daemon with fuzzy history

usage: clipd [command]
  (none)      start the daemon (or report that it runs)
  toggle      show/hide the search popup
  show, hide  explicit popup control
  settings    open preferences
  list        print history (id, pin, kind, preview)
  get ID      print an entry's full text
  save ID F   write an image entry as PNG to file F
  copy ID     put an entry back on the clipboard
  pin ID / unpin ID / rm ID
  clear       delete all unpinned entries
  quit        stop the daemon
  version     print version
"""


class ClipdApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        )

    # -- lifecycle ---------------------------------------------------------

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self.hold()  # stay alive with no visible window
        Gtk.Window.set_default_icon_name(APP_ID)  # hicolor icon, see data/
        self._follow_system_theme()
        self._config = Config.load()
        self._store = Store(db_path())
        display = Gdk.Display.get_default()
        assert display is not None
        self._clipboard = ClipboardService(
            display.get_clipboard(), self._store, self._config, self._on_new_entry
        )
        self._paster = Paster()
        dresser = WindowDresser()
        self._window = ClipWindow(
            self,
            self._store,
            self._config,
            dresser,
            on_activate=self._activate_entry,
            on_settings=self._open_settings,
        )
        self._menu = TrayMenu(
            self,
            dresser,
            [
                ("Show history", self._window.popup),
                ("Settings", self._open_settings),
                ("Quit", self.quit),
            ],
        )
        self._clipboard.start()
        TrayIcon(self._on_tray_click).start()
        _LOG.info("clipd %s ready (%d entries)", __version__, self._store.count())

    def _follow_system_theme(self) -> None:
        """Track the desktop dark/light preference from GSettings directly.

        libadwaita only listens to the settings portal; under dwm no portal
        may be running, which would silently pin the UI to light. GSettings
        is the same source of truth the GTK portal backend reads anyway.
        """
        source = Gio.SettingsSchemaSource.get_default()
        if source is None or source.lookup("org.gnome.desktop.interface", True) is None:
            return
        self._interface_settings = settings = Gio.Settings.new("org.gnome.desktop.interface")

        def apply(*_args: object) -> None:
            scheme = settings.get_string("color-scheme")
            manager = Adw.StyleManager.get_default()
            if scheme == "prefer-dark":
                manager.set_color_scheme(Adw.ColorScheme.PREFER_DARK)
            elif scheme == "prefer-light":
                manager.set_color_scheme(Adw.ColorScheme.PREFER_LIGHT)
            else:
                manager.set_color_scheme(Adw.ColorScheme.DEFAULT)

        settings.connect("changed::color-scheme", apply)
        apply()

    def do_shutdown(self) -> None:
        self._store.close()
        Adw.Application.do_shutdown(self)

    def do_activate(self) -> None:
        pass  # everything goes through do_command_line

    # -- events ------------------------------------------------------------

    def _on_new_entry(self, _entry: Entry, _created: bool) -> None:
        if self._window.get_visible():
            self._window.refresh()

    def _on_tray_click(self, button: int) -> None:
        _LOG.debug("tray click dispatched to app: button=%d", button)
        if button == 1:
            self._window.toggle()
        elif button == 3:
            self._menu.popup_at_pointer()

    def _activate_entry(self, entry: Entry) -> None:
        self._clipboard.copy_entry(entry)
        self._window.dismiss()
        if self._config.auto_paste:
            GLib.timeout_add(_PASTE_DELAY_MS, self._paste_into_target)

    def _paste_into_target(self) -> bool:
        shift = self._config.terminal_shift_paste and self._paster.focused_is_terminal()
        self._paster.paste(shift)
        return False

    def _open_settings(self) -> None:
        if not self._window.get_visible():
            self._window.popup()
        dialog = SettingsDialog(self._config, self._apply_config, self._clear_history)
        dialog.present(self._window)

    def _apply_config(self) -> None:
        self._store.prune(self._config.history_cap)
        if self._window.get_visible():
            self._window.refresh()

    def _clear_history(self) -> None:
        removed = self._store.clear_unpinned()
        _LOG.info("cleared %d unpinned entries", removed)
        self._window.refresh()

    # -- CLI ---------------------------------------------------------------

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        argv = command_line.get_arguments()
        command, args = (argv[1], argv[2:]) if len(argv) > 1 else ("daemon", [])
        try:
            return self._dispatch(command_line, command, args)
        except (ValueError, IndexError):
            command_line.print_literal(_HELP)
            return 2

    def _dispatch(self, out: Gio.ApplicationCommandLine, command: str, args: list[str]) -> int:
        if command == "daemon":
            if out.get_is_remote():
                out.print_literal("clipd: daemon already running\n")
            return 0
        if command in ("help", "--help", "-h"):
            out.print_literal(_HELP)
        elif command in ("version", "--version"):
            out.print_literal(f"clipd {__version__}\n")
        elif command == "toggle":
            self._window.toggle()
        elif command == "show":
            self._window.popup()
        elif command == "hide":
            self._window.dismiss()
        elif command == "settings":
            self._open_settings()
        elif command == "quit":
            self.quit()
        elif command == "list":
            for e in self._store.entries():
                flat = e.preview.replace("\n", " ")
                pin = "*" if e.pinned else "-"
                out.print_literal(f"{e.id}\t{pin}\t{e.kind}\t{flat[:120]}\n")
        elif command == "clear":
            out.print_literal(f"removed {self._store.clear_unpinned()} entries\n")
            self._refresh_if_visible()
        elif command in ("get", "save", "copy", "pin", "unpin", "rm"):
            return self._entry_command(out, command, args)
        else:
            out.print_literal(_HELP)
            return 2
        return 0

    def _entry_command(
        self, out: Gio.ApplicationCommandLine, command: str, args: list[str]
    ) -> int:
        entry = self._store.get(int(args[0]))
        if entry is None:
            out.print_literal(f"clipd: no entry {args[0]}\n")
            return 1
        if command == "get":
            if entry.kind == KIND_IMAGE:
                out.print_literal(f"[{entry.preview}] use: clipd save {entry.id} out.png\n")
            else:
                out.print_literal(entry.text + "\n")
        elif command == "save":
            data = self._store.data(entry.id)
            if entry.kind != KIND_IMAGE or data is None:
                out.print_literal("clipd: not an image entry\n")
                return 1
            path = GLib.build_filenamev([out.get_cwd() or "/", args[1]])
            if args[1].startswith("/"):
                path = args[1]
            with open(path, "wb") as fh:
                fh.write(data)
            out.print_literal(f"wrote {path}\n")
        elif command == "copy":
            if not self._clipboard.copy_entry(entry):
                return 1
        elif command == "pin":
            self._store.set_pinned(entry.id, True)
        elif command == "unpin":
            self._store.set_pinned(entry.id, False)
        elif command == "rm":
            self._store.delete(entry.id)
        self._refresh_if_visible()
        return 0

    def _refresh_if_visible(self) -> None:
        if self._window.get_visible():
            self._window.refresh()


def main() -> int:
    log.setup()
    return ClipdApp().run(sys.argv)
