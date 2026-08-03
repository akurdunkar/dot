"""Tray-anchored calendar panel: an override-redirect window plus a seat grab.

dwm tiles every window it manages, and this dwm binary interns only
``_NET_WM_WINDOW_TYPE_DIALOG`` -- so DOCK, UTILITY and POPUP_MENU hints are all
ignored and a normal toplevel lands in the tiling layout at whatever size the
layout dictates.  ``maprequest()`` returns early on ``wa.override_redirect``,
which makes ``Gtk.WindowType.POPUP`` the one construction dwm never sees.  It
keeps exactly the geometry we ask for and never enters ``_NET_CLIENT_LIST``.

Being unmanaged it is also never focused, so keyboard input and click-outside
dismissal have to come from an explicit :class:`Gdk.Seat` grab.  ``owner_events``
must be ``True``: with ``False`` the grab still succeeds and Escape still works,
but the arrow buttons receive no events at all and clicking them does nothing.

A leaked grab captures the pointer and keyboard for the whole X session and
suppresses dwm's own hotkeys, so every exit path -- including an exception
inside a signal handler, which PyGObject swallows -- must reach :meth:`close`.
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

from ..month import COLUMNS, ROWS, WeekStart, build_month, shift_month, shift_year
from .geometry import Rect, place_panel

log = logging.getLogger(__name__)

_CELL_WIDTH = 30
_CELL_HEIGHT = 26
"""Day box size.  Seven of these across is what makes the grid read as a square."""

_REOPEN_GUARD_MS = 250

_CSS = """
#da-popup {{ background-color: {bg}; }}
#da-popup label {{ color: {fg}; }}
#da-popup .da-title {{ font-weight: bold; padding: 0 8px; }}
#da-popup .da-arrow {{ font-size: 125%; padding: 0 6px; }}
#da-popup .da-weekday {{ font-size: 88%; color: {dim}; }}
#da-popup .da-weeknum {{ font-size: 84%; color: {faint}; padding-right: 4px; }}
#da-popup .da-outside {{ color: {faint}; }}
#da-popup .da-today {{
    background-color: {accent};
    color: {accent_fg};
    border-radius: 4px;
    font-weight: bold;
}}
#da-popup .da-rule {{ background-color: {faint}; min-height: 1px; }}
"""
"""Every class rule is scoped under ``#da-popup`` deliberately.

The base rule needs the id to keep this stylesheet off the rest of the process's
widgets -- it is installed on the whole screen, which is the only place GTK3
lets you add a provider.  But that makes it ``#da-popup label``, specificity
(1,0,1), and a bare ``.da-outside`` at (0,1,0) then loses to it: the dimming
silently does nothing while the panel still looks plausible.  Scoping the class
rules too puts them at (1,1,0), which wins.
"""


class CalendarPopup:
    """Override-redirect panel showing one month at a time.

    Nothing in it is selectable.  The day boxes are labels rather than buttons
    precisely because there is no date to pick -- which also means the panel has
    no focusable child, so every key press lands on the window handler below.
    """

    def __init__(
        self,
        *,
        week_start: WeekStart = WeekStart.MONDAY,
        show_week_numbers: bool = False,
    ) -> None:
        self._week_start = week_start
        self._show_week_numbers = show_week_numbers
        self._today = date.today()
        self._year = self._today.year
        self._month = self._today.month
        self._grabbed = False
        self._closed_at = 0.0

        self._win = Gtk.Window(type=Gtk.WindowType.POPUP)
        self._win.set_name("da-popup")
        # An override-redirect window has no WM to show a title, but setting it
        # makes the panel identifiable in xwininfo/xprop when diagnosing where
        # it actually landed.
        self._win.set_title("da-popup")
        self._win.set_resizable(False)
        self._win.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
            | Gdk.EventMask.SCROLL_MASK
            | Gdk.EventMask.SMOOTH_SCROLL_MASK
        )
        self._win.connect("button-press-event", self._on_button_press)
        self._win.connect("key-press-event", self._on_key_press)
        self._win.connect("scroll-event", self._on_scroll)

        self._title = Gtk.Button(label="")
        self._week_labels: list[Gtk.Label] = []
        self._day_labels: list[list[Gtk.Label]] = []

        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.OUT)
        self._grid = Gtk.Grid(row_spacing=2, column_spacing=1)
        self._grid.set_border_width(8)
        frame.add(self._grid)
        self._win.add(frame)

        self._build()
        self._apply_css()
        self._render()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build(self) -> None:
        """Lay out the fixed grid once.

        Built once and thereafter only relabelled: the row count is fixed at
        six (see :mod:`da.month`), so navigation never needs to add or remove a
        widget -- which it could not safely do anyway while the panel holds the
        seat grab those widgets live under.
        """
        day_column = 1 if self._show_week_numbers else 0
        total_columns = COLUMNS + day_column

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        # Years bracket months, and the doubled glyph takes the coarser step:
        # at this size the nesting and the stroke count are the only things
        # telling a year arrow from a month one.
        year_back = self._arrow_button("«", "Previous year", self._on_year_clicked, -1)
        month_back = self._arrow_button("‹", "Previous month", self._on_month_clicked, -1)
        month_forward = self._arrow_button("›", "Next month", self._on_month_clicked, 1)
        year_forward = self._arrow_button("»", "Next year", self._on_year_clicked, 1)
        # Not focusable, any of them: an override-redirect window gets no focus
        # from the WM, and a focusable child would still draw a focus ring and
        # swallow the arrow keys the window handler wants.
        self._title.set_relief(Gtk.ReliefStyle.NONE)
        self._title.set_can_focus(False)
        self._title.set_hexpand(True)
        self._title.get_style_context().add_class("da-title")
        self._title.set_tooltip_text("Back to today")
        self._title.connect("clicked", self._on_title_clicked)

        header.pack_start(year_back, False, False, 0)
        header.pack_start(month_back, False, False, 0)
        header.pack_start(self._title, True, True, 0)
        header.pack_start(month_forward, False, False, 0)
        header.pack_start(year_forward, False, False, 0)
        self._grid.attach(header, 0, 0, total_columns, 1)

        for column, text in enumerate(self._weekday_labels()):
            label = Gtk.Label(label=text)
            label.get_style_context().add_class("da-weekday")
            label.set_size_request(_CELL_WIDTH, -1)
            self._grid.attach(label, day_column + column, 1, 1, 1)

        rule = Gtk.Box()
        rule.get_style_context().add_class("da-rule")
        self._grid.attach(rule, 0, 2, total_columns, 1)

        for row in range(ROWS):
            if self._show_week_numbers:
                week_label = Gtk.Label(label="")
                week_label.get_style_context().add_class("da-weeknum")
                week_label.set_xalign(1.0)
                self._grid.attach(week_label, 0, 3 + row, 1, 1)
                self._week_labels.append(week_label)

            cells: list[Gtk.Label] = []
            for column in range(COLUMNS):
                label = Gtk.Label(label="")
                label.get_style_context().add_class("da-day")
                label.set_size_request(_CELL_WIDTH, _CELL_HEIGHT)
                self._grid.attach(label, day_column + column, 3 + row, 1, 1)
                cells.append(label)
            self._day_labels.append(cells)

    def _arrow_button(
        self,
        text: str,
        tooltip: str,
        handler: Callable[[Gtk.Button, int], None],
        delta: int,
    ) -> Gtk.Button:
        button = Gtk.Button(label=text)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_can_focus(False)
        button.get_style_context().add_class("da-arrow")
        button.set_tooltip_text(tooltip)
        button.connect("clicked", handler, delta)
        return button

    def _weekday_labels(self) -> tuple[str, ...]:
        return build_month(self._year, self._month, self._week_start).weekday_labels

    def _apply_css(self) -> None:
        """Style from the running theme's colours, resolved to literals.

        The theme colours are looked up and baked into the stylesheet rather
        than referenced as ``@theme_fg_color``: an undefined ``@name`` is a CSS
        parse error that drops the whole declaration, so a theme missing one
        would silently lose the today highlight instead of falling back.
        """
        context = self._win.get_style_context()

        def colour(name: str, fallback: tuple[float, float, float], alpha: float = 1.0) -> str:
            found, rgba = context.lookup_color(name)
            red, green, blue = (rgba.red, rgba.green, rgba.blue) if found else fallback
            return (
                f"rgba({int(red * 255)}, {int(green * 255)}, {int(blue * 255)}, {alpha:.2f})"
            )

        css = _CSS.format(
            bg=colour("theme_bg_color", (0.18, 0.20, 0.21)),
            fg=colour("theme_fg_color", (0.90, 0.90, 0.88)),
            dim=colour("theme_fg_color", (0.90, 0.90, 0.88), 0.70),
            faint=colour("theme_fg_color", (0.90, 0.90, 0.88), 0.38),
            accent=colour("theme_selected_bg_color", (0.29, 0.51, 0.71)),
            accent_fg=colour("theme_selected_fg_color", (1.0, 1.0, 1.0)),
        )

        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode("utf-8"))
        screen = Gdk.Screen.get_default()
        if screen is None:
            log.warning("No default screen; the panel will use unstyled defaults")
            return
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def _render(self) -> None:
        view = build_month(self._year, self._month, self._week_start)
        self._title.set_label(view.title)

        for row, week in enumerate(view.weeks):
            if self._show_week_numbers:
                self._week_labels[row].set_label(str(week.iso_week))
            for column, cell in enumerate(week.days):
                label = self._day_labels[row][column]
                label.set_label(str(cell.date.day))
                context = label.get_style_context()
                context.remove_class("da-outside")
                context.remove_class("da-today")
                if not cell.in_month:
                    context.add_class("da-outside")
                if cell.date == self._today:
                    context.add_class("da-today")

    def set_today(self, today: date) -> None:
        """Move the highlight after a day rollover.

        The view follows into the new month only if it was already showing the
        old one -- if the user has paged away to December, midnight should not
        yank them back.
        """
        was_current = (self._year, self._month) == (self._today.year, self._today.month)
        self._today = today
        if was_current:
            self._year, self._month = today.year, today.month
        self._render()

    def go_today(self) -> None:
        self._year, self._month = self._today.year, self._today.month
        self._render()

    def shift_months(self, delta: int) -> None:
        self._year, self._month = shift_month(self._year, self._month, delta)
        self._render()

    def shift_years(self, delta: int) -> None:
        self._year, self._month = shift_year(self._year, self._month, delta)
        self._render()

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
        # Always open on the current month: a tray calendar opened on whatever
        # month was left showing three days ago is a small lie about the date.
        self.go_today()

        anchor = tray_anchor(icon)
        # Map first: a seat grab on an unmapped window returns NOT_VIEWABLE.
        self._win.show_all()
        width, height = self._win.get_size()
        x, y = place_panel(anchor, width, height, _monitor_at(anchor))
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
            return
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

    def close(self) -> None:
        self.release_grab()
        self._win.hide()
        self._closed_at = _now_ms()

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
    # Interaction
    # ------------------------------------------------------------------

    def _on_month_clicked(self, _button: Gtk.Button, delta: int) -> None:
        self.shift_months(delta)

    def _on_year_clicked(self, _button: Gtk.Button, delta: int) -> None:
        self.shift_years(delta)

    def _on_title_clicked(self, _button: Gtk.Button) -> None:
        self.go_today()

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
        if not inside:
            self.close()
            return True
        # Propagate: presses that land on an arrow button are consumed by the
        # button itself and never reach here.
        return False

    def _on_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        keyval = event.keyval
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_q):
            self.close()
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_Page_Up, Gdk.KEY_h):
            self.shift_months(-1)
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_Page_Down, Gdk.KEY_l):
            self.shift_months(1)
        elif keyval in (Gdk.KEY_Up, Gdk.KEY_k):
            self.shift_years(-1)
        elif keyval in (Gdk.KEY_Down, Gdk.KEY_j):
            self.shift_years(1)
        elif keyval in (Gdk.KEY_Home, Gdk.KEY_t, Gdk.KEY_period):
            self.go_today()
        else:
            return False
        return True

    def _on_scroll(self, _widget: Gtk.Widget, event: Gdk.EventScroll) -> bool:
        step = scroll_step(event)
        if step:
            self.shift_months(-step)  # wheel up goes back in time
        return True


# ----------------------------------------------------------------------
# Gdk plumbing
# ----------------------------------------------------------------------


def _now_ms() -> float:
    return GLib.get_monotonic_time() / 1000.0


def _default_seat() -> Gdk.Seat | None:
    display = Gdk.Display.get_default()
    if display is None:
        return None
    return display.get_default_seat()


def _monitor_at(anchor: Rect) -> Rect | None:
    """Geometry of the monitor holding ``anchor``, if there is a display."""
    display = Gdk.Display.get_default()
    if display is None:
        return None
    monitor = display.get_monitor_at_point(anchor.x, anchor.y) or display.get_monitor(0)
    # The stubs type get_monitor() as non-optional, so strict mode calls this
    # check dead.  The GIR annotates it nullable and it does return None on a
    # display with no monitors -- where an AttributeError would escape a signal
    # handler that is holding the seat grab, and capture the pointer and
    # keyboard for the rest of the X session.
    if monitor is None:  # pyright: ignore[reportUnnecessaryComparison]
        return None
    geo = monitor.get_geometry()
    return Rect(geo.x, geo.y, geo.width, geo.height)


def tray_anchor(icon: Gtk.StatusIcon) -> Rect:
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
        return Rect(area.x, area.y, area.width, area.height)

    seat = _default_seat()
    if seat is not None:
        pointer = seat.get_pointer()
        if pointer is not None:
            _screen, pointer_x, pointer_y = pointer.get_position()
            log.debug("Tray geometry unavailable; anchoring at pointer (%d, %d)", pointer_x, pointer_y)
            return Rect(pointer_x, pointer_y, 1, 1)
    return Rect(0, 0, 1, 1)


def scroll_step(event: Gdk.EventScroll) -> int:
    """``+1`` / ``-1`` / ``0`` from a ``scroll-event``.

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
