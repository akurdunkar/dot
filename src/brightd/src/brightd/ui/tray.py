"""XEmbed system tray icon (Gtk.StatusIcon).

``Gtk.StatusIcon`` is deprecated in GTK3 and is nevertheless the only choice
here: dwm's systray patch speaks XEmbed, and AppIndicator/StatusNotifierItem
icons simply never appear.  The deprecation warnings are silenced deliberately.

Every signal handler is wrapped: PyGObject swallows exceptions raised inside
one, and an exception escaping while the panel holds a seat grab would leave
the pointer and keyboard captured for the entire X session.
"""

from __future__ import annotations

import logging
import warnings
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from ..controller import Controller
from ..types import DisplayKind
from . import icon as icon_mod
from .popup import SliderPopup, scroll_step

log = logging.getLogger(__name__)

_EMBED_CHECKS_SECONDS = (5, 15, 60)
"""Backoff for the embed check.

brightd can easily start before dwm's systray window exists -- from
``autostart.sh``, or during a dwm restart -- so a single one-shot check that
gives up forever would leave the user with no icon and no explanation.
"""

_SCROLL_STEP_PERCENT = 5.0


class TrayIcon:
    """Tray icon: click for sliders, scroll to adjust, right-click for a menu."""

    def __init__(
        self,
        controller: Controller,
        *,
        on_quit: Callable[[], None],
        on_rescan: Callable[[], None] | None = None,
    ) -> None:
        self._controller = controller
        self._on_quit = on_quit
        self._on_rescan = on_rescan
        self._size = 22
        self._menu: Gtk.Menu | None = None
        self._embed_check_index = 0

        self._popup = SliderPopup(self._on_slider_change)
        self.rebuild_rows()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._icon = Gtk.StatusIcon()
            self._icon.set_visible(True)
        self._icon.connect("activate", self._on_activate)
        self._icon.connect("popup-menu", self._on_popup_menu)
        self._icon.connect("size-changed", self._on_size_changed)
        self._icon.connect("scroll-event", self._on_scroll)

        controller.add_listener(self._on_external_change)
        self._refresh_icon()
        GLib.timeout_add_seconds(_EMBED_CHECKS_SECONDS[0], self._check_embedded)

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def _check_embedded(self) -> bool:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            embedded = self._icon.is_embedded()
            if not embedded:
                # Re-assert visibility: a tray that appeared after us only
                # adopts icons that ask again.
                self._icon.set_visible(True)
        if embedded:
            log.debug("Tray icon embedded")
            return False

        self._embed_check_index += 1
        if self._embed_check_index >= len(_EMBED_CHECKS_SECONDS):
            log.warning(
                "Tray icon still not embedded -- no XEmbed systray manager found "
                "(is dwm's systray patch enabled, or trayer running?)"
            )
            return False
        delay = _EMBED_CHECKS_SECONDS[self._embed_check_index]
        log.debug("Tray icon not embedded yet; re-checking in %ds", delay)
        GLib.timeout_add_seconds(delay, self._check_embedded)
        return False

    def _on_size_changed(self, _icon: Gtk.StatusIcon, size: int) -> bool:
        self._size = size
        self._refresh_icon()
        return True

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def rebuild_rows(self) -> None:
        """Push the current display set into the panel."""
        self._popup.set_rows(
            [
                (info.id, info.label, self._controller.percent(info.id))
                for info in self._controller.displays
            ]
        )

    def _refresh_icon(self) -> None:
        percent = self._controller.primary_percent
        pixbuf = icon_mod.render_icon(self._size, percent)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._icon.set_from_pixbuf(pixbuf)
            self._icon.set_tooltip_text(self._tooltip())

    def _tooltip(self) -> str:
        lines = [
            f"{info.label}: {self._controller.percent(info.id):.0f}%"
            for info in self._controller.displays
        ]
        return "brightd\n" + "\n".join(lines) if lines else "brightd — no displays"

    def _on_external_change(self, display_id: str, percent: float) -> None:
        """Controller told us a value moved underneath us (hotkey, other tool)."""
        self._popup.set_from_hardware(display_id, percent)
        self._refresh_icon()

    def _on_slider_change(self, display_id: str, percent: float) -> None:
        self._controller.set_percent(display_id, percent)
        self._refresh_icon()

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _on_activate(self, _icon: Gtk.StatusIcon) -> None:
        try:
            self._popup.toggle(self._icon)
        except Exception:  # noqa: BLE001 -- never leave the seat grabbed
            log.exception("Opening the brightness panel failed")
            self._popup.release_grab()

    def _on_scroll(self, _icon: Gtk.StatusIcon, event: Gdk.EventScroll) -> bool:
        step = scroll_step(event)
        if step:
            target = self._scroll_target()
            if target is not None:
                percent = self._controller.nudge(target, step * _SCROLL_STEP_PERCENT)
                self._popup.set_from_hardware(target, percent)
                self._refresh_icon()
        return True

    def _scroll_target(self) -> str | None:
        """Which display the wheel adjusts: the built-in panel, else the first."""
        for info in self._controller.displays:
            if info.kind is DisplayKind.INTERNAL:
                return info.id
        displays = self._controller.displays
        return displays[0].id if displays else None

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _on_popup_menu(self, _icon: Gtk.StatusIcon, button: int, time: int) -> None:
        menu = Gtk.Menu()

        for info in self._controller.displays:
            item = Gtk.MenuItem(label=f"{info.label} — {self._controller.percent(info.id):.0f}%")
            item.set_sensitive(False)
            menu.append(item)
        if self._controller.displays:
            menu.append(Gtk.SeparatorMenuItem())

        refresh = Gtk.MenuItem(label="Refresh from hardware")
        refresh.connect("activate", self._on_refresh)
        menu.append(refresh)

        if self._on_rescan is not None:
            rescan = Gtk.MenuItem(label="Rescan displays")
            rescan.connect("activate", self._on_rescan_clicked)
            menu.append(rescan)

        menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", self._on_quit_clicked)
        menu.append(quit_item)

        menu.show_all()
        self._menu = menu
        # Positioned at the pointer rather than via Gtk.StatusIcon.position_menu:
        # dwm writes an atom id into _NET_SYSTEM_TRAY_ORIENTATION where the spec
        # wants 0 or 1, so GTK believes the tray is vertical and anchors the menu
        # off the icon's right edge at y=0.
        menu.popup(None, None, None, None, button, time)

    def _on_refresh(self, _item: Gtk.MenuItem) -> None:
        for info in self._controller.displays:
            self._controller.refresh(info.id)
        self.rebuild_rows()
        self._refresh_icon()

    def _on_rescan_clicked(self, _item: Gtk.MenuItem) -> None:
        if self._on_rescan is not None:
            self._on_rescan()

    def _on_quit_clicked(self, _item: Gtk.MenuItem) -> None:
        self._on_quit()

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Hide the icon and guarantee the seat grab is released."""
        self._popup.release_grab()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._icon.set_visible(False)
