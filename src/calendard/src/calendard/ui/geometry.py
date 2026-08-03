"""Panel placement, kept free of GTK so it can be tested without a display.

The caller converts Gdk rectangles into :class:`Rect` and passes the monitor in
explicitly; nothing here queries a screen.
"""

from __future__ import annotations

from typing import NamedTuple

GAP = 2
"""Pixels between the tray icon and the panel."""

EDGE = 4
"""Pixels kept clear of the monitor edges."""


class Rect(NamedTuple):
    x: int
    y: int
    width: int
    height: int


def place_panel(
    anchor: Rect,
    width: int,
    height: int,
    monitor: Rect | None = None,
) -> tuple[int, int]:
    """Top-left corner for a ``width`` x ``height`` panel next to ``anchor``.

    Right-aligned with the anchor and dropped below it, because dwm's tray sits
    in the right corner of a top bar and the anchor rect *is* the bar row -- so
    ``anchor.y + anchor.height`` already clears it.  dwm publishes no
    ``_NET_WORKAREA`` (its "work area" is the whole monitor, bar included),
    which is why the bar cannot be avoided any other way and why the flip to
    above the anchor, for a bottom bar, has to be explicit.

    With no ``monitor`` the unclamped position is returned rather than guessed
    at -- better an off-screen panel that can be diagnosed than one silently
    dragged onto the wrong display.
    """
    x = anchor.x + anchor.width - width
    y = anchor.y + anchor.height + GAP

    if monitor is None:
        return x, y

    if y + height > monitor.y + monitor.height - EDGE:
        y = anchor.y - height - GAP  # a bottom bar: flip above the anchor
    x = max(monitor.x + EDGE, min(x, monitor.x + monitor.width - width - EDGE))
    y = max(monitor.y + EDGE, min(y, monitor.y + monitor.height - height - EDGE))
    return x, y
