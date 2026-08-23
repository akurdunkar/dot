"""Tray context menu: a tiny popup window placed at the pointer.

GTK4 popovers need an anchor widget inside a GTK window, which a raw
XEmbed tray icon is not, so the menu is a frameless window moved next to
the pointer with the X11 dresser. It dismisses on focus loss or Escape.
"""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkX11", "4.0")
from gi.repository import Adw, Gdk, GdkX11, GLib, Gtk

from clipd.x11.wm import WindowDresser

MenuItems = list[tuple[str, Callable[[], None]]]


class TrayMenu(Gtk.Window):
    def __init__(self, app: Adw.Application, dresser: WindowDresser, items: MenuItems) -> None:
        super().__init__(application=app, title="clipd-menu", decorated=False, resizable=False)
        self._dresser = dresser
        self._active_seen = False  # guards against stale FocusOut on re-show
        self.set_hide_on_close(True)
        self.add_css_class("clipd-square")  # see ClipWindow: black corner cutouts
        self.connect("realize", self._on_realize)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_size_request(160, -1)
        for label, callback in items:
            button = Gtk.Button(child=Gtk.Label(label=label, xalign=0.0))
            button.add_css_class("flat")
            button.connect("clicked", self._clicked, callback)
            box.append(button)
        self.set_child(box)

        keys = Gtk.EventControllerKey()
        keys.connect(
            "key-pressed",
            lambda *a: self.set_visible(False) or True if a[1] == Gdk.KEY_Escape else False,
        )
        self.add_controller(keys)
        self.connect("notify::is-active", self._on_active_changed)

    def _on_realize(self, *_args: object) -> None:
        surface = self.get_surface()
        if isinstance(surface, GdkX11.X11Surface):
            # Mark as dialog before first map so dwm floats it, not tiles it.
            self._dresser.make_dialog(surface.get_xid())

    def _clicked(self, _button: Gtk.Button, callback: Callable[[], None]) -> None:
        self.set_visible(False)
        callback()

    def popup_at_pointer(self) -> None:
        self._active_seen = False
        self.present()
        GLib.idle_add(self._place)

    def _place(self) -> bool:
        surface = self.get_surface()
        if isinstance(surface, GdkX11.X11Surface):
            self._dresser.place_near_pointer(
                surface.get_xid(), self.get_width(), self.get_height()
            )
        return False

    def _on_active_changed(self, *_args: object) -> None:
        if self.props.is_active:
            self._active_seen = True
        elif self._active_seen and self.get_visible():
            self.set_visible(False)
