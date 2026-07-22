"""Pure geometry helpers for the layout editor (no GTK dependencies)."""

from __future__ import annotations

import re

MAX_SCALE = 0.3

_MODE_RE = re.compile(r"^\s*(\d+)\s*[xX]\s*(\d+)")


def parse_mode(mode: str) -> tuple[int, int]:
    """Parse a mode string like ``"3440x1440"`` into ``(width, height)``.

    Trailing refresh-rate decorations (``"@60"``, ``"i"``) are tolerated.
    Raises ``ValueError`` for anything that does not start with WxH.
    """
    match = _MODE_RE.match(mode or "")
    if match is None:
        raise ValueError(f"unparseable mode string: {mode!r}")
    return int(match.group(1)), int(match.group(2))


def effective_size(mode: str, rotation: str) -> tuple[int, int]:
    """Mode size with width/height swapped for left/right rotation."""
    w, h = parse_mode(mode)
    if rotation in ("left", "right"):
        return h, w
    return w, h


def bounding_box(
    rects: list[tuple[int, int, int, int]],
) -> tuple[int, int, int, int]:
    """Bounding box ``(minx, miny, maxx, maxy)`` of ``(x, y, w, h)`` rects."""
    if not rects:
        return (0, 0, 0, 0)
    minx = min(r[0] for r in rects)
    miny = min(r[1] for r in rects)
    maxx = max(r[0] + r[2] for r in rects)
    maxy = max(r[1] + r[3] for r in rects)
    return (minx, miny, maxx, maxy)


def compute_scale(
    bounds: tuple[int, int, int, int],
    widget_w: int,
    widget_h: int,
    margin: int = 24,
) -> tuple[float, float, float]:
    """Map virtual coordinates into a widget, centered with a margin.

    Returns ``(scale, offset_x, offset_y)`` such that
    ``widget_xy = virtual_xy * scale + offset``.  The scale is capped at
    ``MAX_SCALE`` so a single monitor does not fill the whole canvas.
    """
    minx, miny, maxx, maxy = bounds
    bw = maxx - minx
    bh = maxy - miny
    avail_w = max(1, widget_w - 2 * margin)
    avail_h = max(1, widget_h - 2 * margin)
    scale = MAX_SCALE
    if bw > 0:
        scale = min(scale, avail_w / bw)
    if bh > 0:
        scale = min(scale, avail_h / bh)
    offset_x = (widget_w - bw * scale) / 2.0 - minx * scale
    offset_y = (widget_h - bh * scale) / 2.0 - miny * scale
    return (scale, offset_x, offset_y)


def snap_position(
    x: int,
    y: int,
    w: int,
    h: int,
    others: list[tuple[int, int, int, int]],
    threshold: int,
) -> tuple[int, int]:
    """Snap a moving ``(x, y, w, h)`` rect against other rects, arandr-style.

    Candidates per axis are edge adjacency (my left to their right, my right
    to their left) and edge alignment (left-left, right-right, top-top,
    bottom-bottom) plus the origin.  The nearest candidate within
    ``threshold`` wins, independently per axis.
    """
    x_candidates = [0]
    y_candidates = [0]
    for ox, oy, ow, oh in others:
        x_candidates.extend((ox + ow, ox - w, ox, ox + ow - w))
        y_candidates.extend((oy + oh, oy - h, oy, oy + oh - h))

    def pick(value: int, candidates: list[int]) -> int:
        best = min(candidates, key=lambda c: abs(c - value))
        return best if abs(best - value) <= threshold else value

    return (pick(x, x_candidates), pick(y, y_candidates))


def normalize_positions(
    positions: dict[str, tuple[int, int]],
    sizes: dict[str, tuple[int, int]],
    enabled: dict[str, bool],
) -> dict[str, tuple[int, int]]:
    """Shift all positions so the enabled outputs' min x/y become 0.

    xrandr requires non-negative coordinates; disabled outputs are shifted
    by the same delta so relative placement survives re-enabling.  ``sizes``
    is unused (positions are top-left corners) but kept for a uniform
    signature.  If nothing is enabled, positions are returned unchanged.
    """
    active = [name for name, on in enabled.items() if on and name in positions]
    if not active:
        return dict(positions)
    dx = min(positions[name][0] for name in active)
    dy = min(positions[name][1] for name in active)
    return {name: (px - dx, py - dy) for name, (px, py) in positions.items()}
