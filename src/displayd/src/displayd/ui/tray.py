"""XEmbed system tray icon (Gtk.StatusIcon) for displayd.

Gtk.StatusIcon is deprecated in GTK3, but it is the only tray protocol the
dwm systray patch understands (AppIndicator/StatusNotifier icons do not
show), so deprecation warnings are deliberately silenced.
"""

from __future__ import annotations

import concurrent.futures
import logging
import warnings
from typing import TYPE_CHECKING, Callable, Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from . import icon as icon_mod

if TYPE_CHECKING:
    from ..engine import Engine, EngineState

log = logging.getLogger(__name__)

_EMBED_CHECK_SECONDS = 5


class TrayIcon:
    """Tray icon exposing profile switching, the editor, and pause/quit."""

    def __init__(self, engine: Engine, on_quit: Callable[[], None]) -> None:
        self._engine = engine
        self._on_quit = on_quit
        self._menu: Optional[Gtk.Menu] = None
        self._size = 22
        self._last_state = engine.state
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._icon = Gtk.StatusIcon()
            self._icon.set_visible(True)
        self._icon.connect("activate", self._on_activate)
        self._icon.connect("popup-menu", self._on_popup_menu)
        self._icon.connect("size-changed", self._on_size_changed)
        self._apply_state(engine.state)
        engine.add_state_listener(lambda s: GLib.idle_add(self._on_state, s))
        GLib.timeout_add_seconds(_EMBED_CHECK_SECONDS, self._check_embedded)

    def _check_embedded(self) -> bool:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            embedded = self._icon.is_embedded()
        if not embedded:
            log.warning(
                "Tray icon is not embedded after %d s -- no XEmbed systray "
                "manager found (dwm systray patch / trayer running?)",
                _EMBED_CHECK_SECONDS,
            )
        return False

    def _on_size_changed(self, _icon: Gtk.StatusIcon, size: int) -> bool:
        self._size = size
        self._update_icon()
        return True

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def _on_state(self, state: EngineState) -> bool:
        self._apply_state(state)
        return False

    def _apply_state(self, state: EngineState) -> None:
        self._last_state = state
        tooltip = f"displayd — {state.matched_profile or 'no profile'}"
        if state.paused:
            tooltip += " (paused)"
        elif state.in_sync:
            tooltip += " (in sync)"
        else:
            tooltip += " (out of sync)"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._icon.set_tooltip_text(tooltip)
        self._update_icon()

    def _update_icon(self) -> None:
        state = self._last_state
        if state.paused:
            fill = icon_mod.FILL_PAUSED
        elif state.in_sync:
            fill = icon_mod.FILL_IN_SYNC
        else:
            fill = icon_mod.FILL_OUT_OF_SYNC
        pixbuf = icon_mod.render_icon(self._size, fill)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._icon.set_from_pixbuf(pixbuf)

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _on_activate(self, _icon: Gtk.StatusIcon) -> None:
        self._popup(0, Gtk.get_current_event_time())

    def _on_popup_menu(self, _icon: Gtk.StatusIcon, button: int, time: int) -> None:
        self._popup(button, time)

    def _popup(self, button: int, time: int) -> None:
        menu = self._build_menu()
        self._menu = menu
        menu.show_all()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            menu.popup(None, None, Gtk.StatusIcon.position_menu, self._icon, button, time)

    def _build_menu(self) -> Gtk.Menu:
        state = self._engine.state
        menu = Gtk.Menu()

        count = state.topology.monitor_count if state.topology is not None else 0
        noun = "monitor" if count == 1 else "monitors"
        header = Gtk.MenuItem(
            label=f"{count} {noun} — profile: {state.matched_profile or 'none'}"
        )
        header.set_sensitive(False)
        menu.append(header)

        if state.profiles:
            menu.append(Gtk.SeparatorMenuItem())
        for profile in state.profiles:
            marker = "● " if profile.name == state.matched_profile else "  "
            item = Gtk.MenuItem(label=marker + profile.name)
            item.connect("activate", self._on_apply_profile, profile.name)
            menu.append(item)

        menu.append(Gtk.SeparatorMenuItem())

        editor_item = Gtk.MenuItem(label="Open layout editor…")
        editor_item.connect("activate", self._on_open_editor)
        menu.append(editor_item)

        save_item = Gtk.MenuItem(label="Save current layout…")
        save_item.connect("activate", self._on_save_layout)
        menu.append(save_item)

        sync_item = Gtk.MenuItem(label="Sync now")
        sync_item.connect("activate", self._on_sync_now)
        menu.append(sync_item)

        pause_item = Gtk.CheckMenuItem(label="Pause automatic apply")
        pause_item.set_active(state.paused)
        pause_item.connect("toggled", self._on_pause_toggled)
        menu.append(pause_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _i: self._on_quit())
        menu.append(quit_item)

        return menu

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_apply_profile(self, _item: Gtk.MenuItem, name: str) -> None:
        self._watch(self._engine.apply_profile(name), f"apply profile {name!r}")

    def _on_open_editor(self, _item: Gtk.MenuItem) -> None:
        from .editor import LayoutEditorWindow

        LayoutEditorWindow.open(self._engine)

    def _on_sync_now(self, _item: Gtk.MenuItem) -> None:
        self._watch(self._engine.sync_now(), "sync now")

    def _on_pause_toggled(self, item: Gtk.CheckMenuItem) -> None:
        self._engine.set_paused(item.get_active())

    def _on_save_layout(self, _item: Gtk.MenuItem) -> None:
        state = self._engine.state
        dialog = Gtk.Dialog(title="Save current layout", modal=True)
        dialog.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("_Save", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)
        entry = Gtk.Entry()
        entry.set_text(state.matched_profile or "layout")
        entry.set_activates_default(True)
        spin = Gtk.SpinButton.new_with_range(0, 100, 1)
        spin.set_value(0)
        grid.attach(Gtk.Label(label="Name", halign=Gtk.Align.END), 0, 0, 1, 1)
        grid.attach(entry, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Priority", halign=Gtk.Align.END), 0, 1, 1, 1)
        grid.attach(spin, 1, 1, 1, 1)
        dialog.get_content_area().add(grid)
        dialog.show_all()

        if dialog.run() == Gtk.ResponseType.OK:
            name = entry.get_text().strip() or "layout"
            priority = spin.get_value_as_int()
            self._watch(
                self._engine.snapshot_current(name, priority),
                f"snapshot layout {name!r}",
            )
        dialog.destroy()

    # ------------------------------------------------------------------
    # Future plumbing
    # ------------------------------------------------------------------

    def _watch(self, future: concurrent.futures.Future, action: str) -> None:
        future.add_done_callback(
            lambda f: GLib.idle_add(self._log_result, f, action)
        )

    @staticmethod
    def _log_result(future: concurrent.futures.Future, action: str) -> bool:
        try:
            exc = future.exception()
        except concurrent.futures.CancelledError as cancelled:
            exc = cancelled
        if exc is not None:
            log.error("Tray action %s failed: %s", action, exc)
        return False
