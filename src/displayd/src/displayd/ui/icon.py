"""Runtime-rendered tray icon (Cairo -> GdkPixbuf).

Icon themes on minimal setups often lack the standard display icon names,
which leaves Gtk.StatusIcon embedded but invisible.  Drawing the glyph
ourselves works everywhere and stays crisp at whatever size the systray
reports.  The screen fill doubles as a state indicator.
"""

from __future__ import annotations

import cairo
import gi

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf

# Screen fill by daemon state; frame/stand stay light for dark bars.
FILL_IN_SYNC = (0.23, 0.43, 0.65)      # muted blue, matches the editor canvas
FILL_OUT_OF_SYNC = (0.88, 0.63, 0.19)  # amber
FILL_PAUSED = (0.45, 0.45, 0.45)       # gray
FRAME = (0.92, 0.92, 0.92)


def _rounded_rect(cr: cairo.Context, x: float, y: float, w: float, h: float, r: float) -> None:
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


def render_icon(size: int, fill: tuple[float, float, float]) -> GdkPixbuf.Pixbuf:
    """Draw a monitor glyph into a pixbuf of ``size`` x ``size`` pixels."""
    size = max(8, size)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surface)
    s = size / 16.0  # all coordinates below are on a 16x16 design grid

    # Screen: light frame with a state-colored panel inside.
    _rounded_rect(cr, 1.0 * s, 2.0 * s, 14.0 * s, 10.0 * s, 1.5 * s)
    cr.set_source_rgb(*FRAME)
    cr.fill()
    _rounded_rect(cr, 2.2 * s, 3.2 * s, 11.6 * s, 7.6 * s, 0.8 * s)
    cr.set_source_rgb(*fill)
    cr.fill()

    # Stand and base.
    cr.set_source_rgb(*FRAME)
    cr.rectangle(7.0 * s, 12.0 * s, 2.0 * s, 1.6 * s)
    cr.fill()
    _rounded_rect(cr, 4.5 * s, 13.6 * s, 7.0 * s, 1.4 * s, 0.7 * s)
    cr.fill()

    surface.flush()
    return Gdk.pixbuf_get_from_surface(surface, 0, 0, size, size)
