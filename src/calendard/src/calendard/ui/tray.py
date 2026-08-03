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
from datetime import date
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from ..month import WeekStart
from . import icon as icon_mod
from .popup import CalendarPopup, scroll_step

log = logging.getLogger(__name__)

_EMBED_CHECKS_SECONDS = (5, 15, 60)
"""Backoff for the embed check.

calendard can easily start before dwm's systray window exists -- from ``autostart.sh``,
or during a dwm restart -- so a single one-shot check that gives up forever
would leave the user with no icon and no explanation.
"""


class TrayIcon:
    """Tray icon: click for the calendar, scroll to page months, right-click for a menu."""

    def __init__(
        self,
        *,
        on_quit: Callable[[], None],
        week_start: WeekStart = WeekStart.MONDAY,
        show_week_numbers: bool = False,
    ) -> None:
        self._on_quit = on_quit
        self._today = date.today()
        self._size = 22
        self._menu: Gtk.Menu | None = None
        self._embed_check_index = 0

        self._popup = CalendarPopup(week_start=week_start, show_week_numbers=show_week_numbers)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._icon = Gtk.StatusIcon()
            self._icon.set_visible(True)
        self._icon.connect("activate", self._on_activate)
        self._icon.connect("popup-menu", self._on_popup_menu)
        self._icon.connect("size-changed", self._on_size_changed)
        self._icon.connect("scroll-event", self._on_scroll)

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

    def set_today(self, today: date) -> None:
        """Day rolled over: redraw the glyph and move the panel's highlight."""
        self._today = today
        self._popup.set_today(today)
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        pixbuf = icon_mod.render_icon(self._size, self._today.day)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._icon.set_from_pixbuf(pixbuf)
            self._icon.set_tooltip_text(self._tooltip())

    def _tooltip(self) -> str:
        # Built from parts rather than one strftime: "%-d" is a glibc extension
        # and "%d" would render a zero-padded "03 August".
        weekday = self._today.strftime("%A")
        month = self._today.strftime("%B")
        iso = self._today.isocalendar()
        return (
            f"{weekday}, {self._today.day} {month} {self._today.year}\n"
            f"{self._today.isoformat()} · week {iso.week}"
        )

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _on_activate(self, _icon: Gtk.StatusIcon) -> None:
        try:
            self._popup.toggle(self._icon)
        except Exception:  # noqa: BLE001 -- never leave the seat grabbed
            log.exception("Opening the calendar panel failed")
            self._popup.release_grab()

    def _on_scroll(self, _icon: Gtk.StatusIcon, event: Gdk.EventScroll) -> bool:
        # Only while the panel is open: scrolling months with nothing on screen
        # has no visible effect, and opening on scroll would fire every time the
        # pointer crossed the bar mid-scroll.
        if not self._popup.visible:
            return True
        step = scroll_step(event)
        if step:
            self._popup.shift_months(-step)  # wheel up goes back in time
        return True

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _on_popup_menu(self, _icon: Gtk.StatusIcon, button: int, time: int) -> None:
        menu = Gtk.Menu()

        today_item = Gtk.MenuItem(label=self._today.isoformat())
        today_item.set_sensitive(False)
        menu.append(today_item)
        menu.append(Gtk.SeparatorMenuItem())

        show = Gtk.MenuItem(label="Show today")
        show.connect("activate", self._on_show_today)
        menu.append(show)

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

    def _on_show_today(self, _item: Gtk.MenuItem) -> None:
        try:
            if self._popup.visible:
                self._popup.go_today()
            else:
                self._popup.open(self._icon)
        except Exception:  # noqa: BLE001 -- never leave the seat grabbed
            log.exception("Opening the calendar panel failed")
            self._popup.release_grab()

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
