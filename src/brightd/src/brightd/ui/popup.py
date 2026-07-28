"""Tray-anchored brightness panel: an override-redirect window plus a seat grab.

dwm tiles every window it manages, and this dwm binary interns only
``_NET_WM_WINDOW_TYPE_DIALOG`` -- so DOCK, UTILITY and POPUP_MENU hints are all
ignored and a normal toplevel lands in the tiling layout at whatever size the
layout dictates.  ``maprequest()`` returns early on ``wa.override_redirect``,
which makes ``Gtk.WindowType.POPUP`` the one construction dwm never sees.  It
keeps exactly the geometry we ask for and never enters ``_NET_CLIENT_LIST``.

Being unmanaged it is also never focused, so keyboard input and click-outside
dismissal have to come from an explicit :class:`Gdk.Seat` grab.  ``owner_events``
must be ``True``: with ``False`` the grab still succeeds and Escape still works,
but the sliders receive no events at all and dragging silently does nothing.

A leaked grab captures the pointer and keyboard for the whole X session and
suppresses dwm's own hotkeys, so every exit path -- including an exception
inside a signal handler, which PyGObject swallows -- must reach :meth:`close`.
"""

from __future__ import annotations

import logging
import warnings
from typing import Callable, Sequence

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

log = logging.getLogger(__name__)

_GAP = 2
"""Pixels between the tray icon and the panel."""

_EDGE = 4
"""Pixels kept clear of the monitor edges."""

_SLIDER_WIDTH = 220
_REOPEN_GUARD_MS = 250

ChangeHandler = Callable[[str, float], None]

Row = tuple[str, str, float]
"""``(display_id, label, percent)``."""


class SliderPopup:
    """Override-redirect panel with one brightness slider per display."""

    def __init__(self, on_change: ChangeHandler) -> None:
        self._on_change = on_change
        self._scales: dict[str, Gtk.Scale] = {}
        self._handlers: dict[str, int] = {}
        self._rows: list[Row] = []
        self._pending_rows: list[Row] | None = None
        self._grabbed = False
        self._closed_at = 0.0

        self._win = Gtk.Window(type=Gtk.WindowType.POPUP)
        self._win.set_name("brightd-slider-popup")
        # An override-redirect window has no WM to show a title, but setting it
        # makes the panel identifiable in xwininfo/xprop when diagnosing where
        # it actually landed.
        self._win.set_title("brightd-slider-popup")
        self._win.set_resizable(False)
        self._win.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self._win.connect("button-press-event", self._on_button_press)
        self._win.connect("key-press-event", self._on_key_press)

        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.OUT)
        self._grid = Gtk.Grid(row_spacing=6, column_spacing=10)
        self._grid.set_border_width(10)
        frame.add(self._grid)
        self._win.add(frame)

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def set_rows(self, rows: Sequence[Row]) -> None:
        """Rebuild the panel's sliders.

        Rebuilding while the panel is grabbed would destroy the very widgets
        holding the grab, so a hotplug that arrives mid-interaction is deferred
        until the panel closes.
        """
        if self.visible:
            self._pending_rows = list(rows)
            return
        self._build(list(rows))

    def _build(self, rows: list[Row]) -> None:
        for child in self._grid.get_children():
            self._grid.remove(child)
        self._scales.clear()
        self._handlers.clear()
        self._rows = rows

        for index, (display_id, label_text, percent) in enumerate(rows):
            label = Gtk.Label(label=label_text)
            label.set_xalign(0.0)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            # draw_value=False keeps the entire widget height grabbable; with
            # the value drawn, the top third of the allocation is dead space
            # that ignores presses.
            scale.set_draw_value(False)
            scale.set_size_request(_SLIDER_WIDTH, -1)
            scale.set_value(percent)
            handler = scale.connect("value-changed", self._on_scale_changed, display_id)
            self._grid.attach(label, 0, index, 1, 1)
            self._grid.attach(scale, 1, index, 1, 1)
            self._scales[display_id] = scale
            self._handlers[display_id] = handler

    def set_from_hardware(self, display_id: str, percent: float) -> None:
        """Reflect an externally applied change without re-emitting it.

        The signal is blocked rather than filtered with a flag: ``set_value``
        emits ``value-changed`` synchronously, and any guard that merely
        *ignores* the echo still lets a non-idempotent percent round-trip walk
        the value away from where the user put it.
        """
        scale = self._scales.get(display_id)
        handler = self._handlers.get(display_id)
        if scale is None or handler is None:
            return
        scale.handler_block(handler)
        try:
            scale.set_value(percent)
        finally:
            # PyGObject-stubs types handler_block but leaves handler_unblock as
            # a bare *args signature, so strict mode cannot see through it.
            scale.handler_unblock(handler)  # pyright: ignore[reportUnknownMemberType]

    def _on_scale_changed(self, scale: Gtk.Scale, display_id: str) -> None:
        self._on_change(display_id, scale.get_value())

    # ------------------------------------------------------------------
    # Show and hide
    # ------------------------------------------------------------------

    @property
    def visible(self) -> bool:
        return self._win.get_visible()

    def toggle(self, icon: Gtk.StatusIcon) -> None:
        """Left-click entry point.

        Clicking the icon while the panel is open does not re-fire ``activate``
        -- the grab delivers that press to the panel as an outside click, which
        closes it -- so a bare open/close toggle would immediately reopen.  The
        guard window absorbs that stray activate.
        """
        if self.visible:
            self.close()
            return
        if _now_ms() - self._closed_at < _REOPEN_GUARD_MS:
            return
        self.open(icon)

    def open(self, icon: Gtk.StatusIcon) -> None:
        if not self._scales:
            log.warning("No displays to show; not opening the panel")
            return
        anchor = tray_anchor(icon)
        # Map first: a seat grab on an unmapped window returns NOT_VIEWABLE.
        self._win.show_all()
        width, height = self._win.get_size()
        x, y = place_panel(anchor, width, height)
        self._win.move(x, y)

        gdk_window = self._win.get_window()
        if gdk_window is None:  # cannot happen after show_all(), but keeps types honest
            log.error("Panel has no GdkWindow after show_all(); aborting open")
            self._win.hide()
            return
        gdk_window.move(x, y)
        gdk_window.raise_()
        log.debug("Panel at (%d, %d) %dx%d from anchor %r", x, y, width, height, anchor)

        seat = _default_seat()
        if seat is None:
            # Without a grab the panel still shows, but it is override-redirect
            # and therefore never focused, so Escape and click-outside are dead.
            log.warning("No Gdk seat available; the panel cannot grab input")
        else:
            status = seat.grab(gdk_window, Gdk.SeatCapabilities.ALL, True, None, None, None)
            self._grabbed = status == Gdk.GrabStatus.SUCCESS
            if self._grabbed:
                log.debug("Seat grab acquired")
            else:
                log.warning(
                    "Seat grab failed (%s); the panel will not dismiss on "
                    "click-outside or Escape",
                    status.value_nick,
                )

        first = next(iter(self._scales.values()), None)
        if first is not None:
            first.grab_focus()

    def close(self) -> None:
        self.release_grab()
        self._win.hide()
        self._closed_at = _now_ms()
        if self._pending_rows is not None:
            self._build(self._pending_rows)
            self._pending_rows = None

    def release_grab(self) -> None:
        """Drop the seat grab.  Safe to call repeatedly and from a signal handler.

        Exposed separately so shutdown paths can guarantee the pointer and
        keyboard are released even if the panel is mid-teardown.
        """
        if not self._grabbed:
            return
        self._grabbed = False
        seat = _default_seat()
        if seat is not None:
            seat.ungrab()

    # ------------------------------------------------------------------
    # Dismissal
    # ------------------------------------------------------------------

    def _on_button_press(self, widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        # Dismiss on press, never on release: ``Gtk.StatusIcon::activate`` fires
        # on button press, so the matching release of the opening click is
        # delivered here at the tray icon's coordinates -- outside the panel.
        # A release-based dismissal closes the panel the instant it opens.
        gdk_window = widget.get_window()
        if gdk_window is None:
            return False
        _, origin_x, origin_y = gdk_window.get_origin()
        alloc = widget.get_allocation()
        inside = (
            origin_x <= event.x_root < origin_x + alloc.width
            and origin_y <= event.y_root < origin_y + alloc.height
        )
        log.debug(
            "Panel button press at (%.0f, %.0f) inside=%s", event.x_root, event.y_root, inside
        )
        if not inside:
            self.close()
            return True
        return False

    def _on_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        log.debug("Panel key press: keyval=%d", event.keyval)
        if event.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False


# ----------------------------------------------------------------------
# Positioning
# ----------------------------------------------------------------------


def _now_ms() -> float:
    return GLib.get_monotonic_time() / 1000.0


def _default_seat() -> Gdk.Seat | None:
    display = Gdk.Display.get_default()
    if display is None:
        return None
    return display.get_default_seat()


def tray_anchor(icon: Gtk.StatusIcon) -> Gdk.Rectangle:
    """Screen rect to hang the panel off, from the tray icon or the pointer.

    ``Gtk.StatusIcon.get_geometry()`` does work with dwm's XEmbed systray, but
    it reports ``ok=True`` with a 1x1 rectangle for the first moments after
    ``set_visible(True)``, before the tray assigns a size -- checking only
    ``ok`` anchors the panel to a one-pixel phantom.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ok, _screen, area, _orientation = icon.get_geometry()
    if ok and area.width > 1 and area.height > 1:
        return area

    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = 0, 0, 1, 1
    seat = _default_seat()
    if seat is not None:
        pointer = seat.get_pointer()
        if pointer is not None:
            _screen, px, py = pointer.get_position()
            rect.x, rect.y = px, py
            log.debug("Tray geometry unavailable; anchoring at pointer (%d, %d)", px, py)
    return rect


def place_panel(anchor: Gdk.Rectangle, width: int, height: int) -> tuple[int, int]:
    """Top-left corner for a ``width`` x ``height`` panel next to ``anchor``.

    Right-aligned with the anchor and dropped below it, because dwm's tray sits
    in the right corner of a top bar and the anchor rect *is* the bar row -- so
    ``anchor.y + anchor.height`` already clears it.  dwm publishes no
    ``_NET_WORKAREA`` (the "work area" is the whole monitor, bar included),
    which is why the bar cannot be avoided any other way and why the flip has
    to be explicit.
    """
    x = anchor.x + anchor.width - width
    y = anchor.y + anchor.height + _GAP

    display = Gdk.Display.get_default()
    monitor = None
    if display is not None:
        monitor = display.get_monitor_at_point(anchor.x, anchor.y) or display.get_monitor(0)
    if monitor is None:
        return x, y

    geo = monitor.get_geometry()
    if y + height > geo.y + geo.height - _EDGE:
        y = anchor.y - height - _GAP  # a bottom bar: flip above the anchor
    x = max(geo.x + _EDGE, min(x, geo.x + geo.width - width - _EDGE))
    y = max(geo.y + _EDGE, min(y, geo.y + geo.height - height - _EDGE))
    return x, y


def scroll_step(event: Gdk.EventScroll) -> int:
    """``+1`` / ``-1`` / ``0`` from a tray ``scroll-event``.

    A wheel reports discrete UP/DOWN; a libinput touchpad reports SMOOTH, whose
    ``direction`` carries no useful information and whose delta must be read
    instead.
    """
    if event.direction == Gdk.ScrollDirection.UP:
        return 1
    if event.direction == Gdk.ScrollDirection.DOWN:
        return -1
    if event.direction == Gdk.ScrollDirection.SMOOTH:
        ok, _dx, dy = event.get_scroll_deltas()
        if ok and dy:
            return -1 if dy > 0 else 1
    return 0
