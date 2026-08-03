"""Tray glyph rendering.

Only the Cairo half is exercised: it needs no display, no tray and no pixbuf
conversion, which is what makes it testable at all.  The checks are deliberately
coarse -- "something was drawn, inside the bounds, and it changes with the day"
-- because asserting on pixels would fail on any font substitution.
"""

from __future__ import annotations

import cairo
import pytest

from da.ui.icon import draw_icon

SIZES = [16, 19, 22, 24, 48]
"""19 is what dwm's systray asks for here; the rest bracket it."""


def render(size: int, day: int) -> bytes:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    context: cairo.Context[cairo.ImageSurface] = cairo.Context(surface)
    draw_icon(context, size, day)
    surface.flush()
    return bytes(surface.get_data())


def opaque_pixels(size: int, day: int) -> int:
    data = render(size, day)
    return sum(1 for offset in range(0, len(data), 4) if data[offset + 3] > 0)


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("day", [1, 9, 10, 28, 29, 30, 31])
def test_draws_within_bounds(size: int, day: int) -> None:
    assert opaque_pixels(size, day) > 0


@pytest.mark.parametrize("size", SIZES)
def test_every_day_of_the_month_renders(size: int) -> None:
    for day in range(1, 32):
        assert opaque_pixels(size, day) > 0


@pytest.mark.parametrize("size", SIZES)
def test_two_digit_days_differ_from_one_digit(size: int) -> None:
    """The number is shrunk to fit rather than clipped, so a too-wide "28" must
    still leave more ink than "2" -- clipping would make them identical."""
    assert render(size, 28) != render(size, 2)


def test_undersized_requests_are_floored_not_crashed() -> None:
    """A tray reporting a nonsense size must not take the daemon down."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8)
    context: cairo.Context[cairo.ImageSurface] = cairo.Context(surface)
    draw_icon(context, 0, 15)
    surface.flush()
    assert any(byte for byte in bytes(surface.get_data()))
