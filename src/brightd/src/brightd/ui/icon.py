"""Runtime-rendered tray icon (Cairo -> GdkPixbuf).

Minimal setups routinely lack the standard icon-theme names, which leaves a
``Gtk.StatusIcon`` embedded but invisible.  Drawing the glyph ourselves works
everywhere and stays crisp at whatever size the systray reports -- dwm's tray
asks for 19x19 here.

The glyph is a sun rather than displayd's monitor rectangle, deliberately:
displayd already occupies an adjacent tray slot, and two similar rectangles
would be indistinguishable at this size.  Brightness is encoded as colour
temperature and ray length rather than as a number, which is illegible at 19px.

``render_icon`` is a pure function so it can be exercised without a tray.
"""

from __future__ import annotations

import math

import cairo
import gi

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf

DIM = (0.42, 0.42, 0.44)
"""Colour at 0%: a cool grey that stays visible on a dark bar."""

BRIGHT = (1.0, 0.84, 0.32)
"""Colour at 100%: warm sunlight."""

_RAYS = 8


def _mix(low: tuple[float, float, float], high: tuple[float, float, float], t: float) -> tuple[float, float, float]:
    return (
        low[0] + (high[0] - low[0]) * t,
        low[1] + (high[1] - low[1]) * t,
        low[2] + (high[2] - low[2]) * t,
    )


def render_icon(size: int, percent: float) -> GdkPixbuf.Pixbuf:
    """Draw a sun glyph at ``percent`` brightness into a ``size`` px pixbuf."""
    size = max(8, size)
    fraction = max(0.0, min(1.0, percent / 100.0))
    colour = _mix(DIM, BRIGHT, fraction)

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr: cairo.Context[cairo.ImageSurface] = cairo.Context(surface)
    s = size / 16.0  # all coordinates below are on a 16x16 design grid
    centre = 8.0 * s

    # Rays: length grows with brightness so the glyph reads at a glance even in
    # a monochrome screenshot, where the colour cue is lost.
    inner = 5.0 * s
    outer = (5.9 + 1.4 * fraction) * s
    cr.set_source_rgb(*colour)
    cr.set_line_width(1.3 * s)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for index in range(_RAYS):
        angle = index * (2.0 * math.pi / _RAYS)
        dx, dy = math.cos(angle), math.sin(angle)
        cr.move_to(centre + dx * inner, centre + dy * inner)
        cr.line_to(centre + dx * outer, centre + dy * outer)
    cr.stroke()

    # Disc.
    cr.arc(centre, centre, 3.5 * s, 0.0, 2.0 * math.pi)
    cr.fill()

    # A dark core at low levels keeps 0% distinguishable from a solid dim disc.
    if fraction < 0.5:
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.35 * (1.0 - fraction * 2.0))
        cr.arc(centre, centre, 1.9 * s, 0.0, 2.0 * math.pi)
        cr.fill()

    surface.flush()
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, size, size)
    if pixbuf is None:  # only on an out-of-memory or zero-sized surface
        raise RuntimeError(f"Could not convert a {size}x{size} surface to a pixbuf")
    return pixbuf
