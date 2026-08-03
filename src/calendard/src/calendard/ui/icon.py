"""Runtime-rendered tray icon (Cairo -> GdkPixbuf).

Minimal setups routinely lack the standard icon-theme names, which leaves a
``Gtk.StatusIcon`` embedded but invisible.  Drawing the glyph ourselves works
everywhere and stays crisp at whatever size the systray reports -- dwm's tray
asks for 19x19 here.

The glyph is a torn-off calendar page carrying the day number, which makes the
tray icon itself the date readout and leaves the panel for navigating.  It is a
page rather than displayd's monitor rectangle or brightd's sun deliberately:
all three sit in adjacent tray slots at 19px, where shape and colour are the
only things that separate them.

:func:`draw_icon` takes a Cairo context so it can be exercised on a plain image
surface, with no display and no tray.
"""

from __future__ import annotations

import math

import cairo
import gi

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf

PAGE = (0.93, 0.93, 0.91)
"""Paper: near-white, so the glyph reads against a dark bar."""

BAND = (0.80, 0.27, 0.25)
"""The page header, in the red every paper calendar uses for it."""

INK = (0.13, 0.13, 0.15)
"""The day number."""

_MIN_SIZE = 8


def _rounded_rect(
    cr: cairo.Context[cairo.ImageSurface],
    x: float,
    y: float,
    width: float,
    height: float,
    radius: float,
) -> None:
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0.0)
    cr.arc(x + width - radius, y + height - radius, radius, 0.0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 1.5 * math.pi)
    cr.close_path()


def draw_icon(cr: cairo.Context[cairo.ImageSurface], size: int, day: int) -> None:
    """Draw the calendar glyph for ``day`` at ``size`` px into ``cr``."""
    size = max(_MIN_SIZE, size)
    s = size / 16.0  # all coordinates below are on a 16x16 design grid

    page_x, page_y = 1.5 * s, 3.0 * s
    page_w, page_h = 13.0 * s, 11.5 * s
    band_h = 3.2 * s

    # Grayscale antialiasing, not the default subpixel: subpixel AA bakes an
    # assumed LCD stripe order and an assumed background into the coverage
    # values, and this pixbuf gets composited onto a tray whose colour we do
    # not know.  Left on, the digits fringe visibly orange and blue at 19px.
    options = cairo.FontOptions()
    options.set_antialias(cairo.ANTIALIAS_GRAY)
    cr.set_font_options(options)

    # Binder rings first, so the page covers where they meet it.  Drawn in the
    # page colour rather than the ink: only the 1.5px above the page edge is
    # ever visible, and dark-on-dark loses it against dwm's bar.
    cr.set_source_rgb(*PAGE)
    cr.set_line_width(1.2 * s)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for ring_x in (5.0 * s, 11.0 * s):
        cr.move_to(ring_x, 1.4 * s)
        cr.line_to(ring_x, 4.2 * s)
    cr.stroke()

    cr.set_source_rgb(*PAGE)
    _rounded_rect(cr, page_x, page_y, page_w, page_h, 1.6 * s)
    cr.fill()

    # The band is the top slice of the page, clipped to it so it inherits the
    # rounded top corners instead of squaring them off.
    cr.save()
    _rounded_rect(cr, page_x, page_y, page_w, page_h, 1.6 * s)
    cr.clip()
    cr.set_source_rgb(*BAND)
    cr.rectangle(page_x, page_y, page_w, band_h)
    cr.fill()
    cr.restore()

    _draw_day(cr, day, s, body_top=page_y + band_h, body_bottom=page_y + page_h)


def _draw_day(
    cr: cairo.Context[cairo.ImageSurface],
    day: int,
    s: float,
    *,
    body_top: float,
    body_bottom: float,
) -> None:
    """Centre the day number in the page body, shrinking it to fit."""
    text = str(day)
    cr.set_source_rgb(*INK)
    cr.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)

    max_width = 9.5 * s
    font_size = 8.6 * s
    cr.set_font_size(font_size)
    extents = cr.text_extents(text)
    if extents.width > max_width:
        # Two-digit days at a small tray size: scale to fit rather than clip,
        # which would silently turn 28 into 2.
        font_size *= max_width / extents.width
        cr.set_font_size(font_size)
        extents = cr.text_extents(text)

    centre_x = 8.0 * s
    centre_y = (body_top + body_bottom) / 2.0
    # Positioned from the ink extents, not the font metrics: digits have no
    # descender, so metric-based centring sits visibly high.
    cr.move_to(
        centre_x - extents.width / 2.0 - extents.x_bearing,
        centre_y - extents.height / 2.0 - extents.y_bearing,
    )
    cr.show_text(text)


def render_icon(size: int, day: int) -> GdkPixbuf.Pixbuf:
    """Render the glyph for ``day`` into a ``size`` px pixbuf."""
    size = max(_MIN_SIZE, size)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr: cairo.Context[cairo.ImageSurface] = cairo.Context(surface)
    draw_icon(cr, size, day)
    surface.flush()

    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, size, size)
    if pixbuf is None:  # only on an out-of-memory or zero-sized surface
        raise RuntimeError(f"Could not convert a {size}x{size} surface to a pixbuf")
    return pixbuf
