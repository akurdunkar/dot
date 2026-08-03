"""Panel placement against a tray anchor.

dwm publishes no ``_NET_WORKAREA``, so nothing here can be delegated to GTK --
which is also why it is worth testing directly.
"""

from __future__ import annotations

from calendard.ui.geometry import EDGE, GAP, Rect, place_panel

MONITOR = Rect(0, 0, 1920, 1080)
"""A single 1080p screen with a top bar."""

TOP_BAR_ICON = Rect(1880, 0, 20, 20)
"""dwm's systray sits at the right end of the bar."""

PANEL = (240, 220)


class TestBelowATopBar:
    def test_drops_below_the_bar(self) -> None:
        _, y = place_panel(TOP_BAR_ICON, *PANEL, MONITOR)
        assert y == TOP_BAR_ICON.y + TOP_BAR_ICON.height + GAP

    def test_right_aligns_with_the_icon(self) -> None:
        """The tray is in the right corner, so growing leftwards is the only
        direction that does not immediately hit the screen edge."""
        x, _ = place_panel(Rect(1600, 0, 20, 20), *PANEL, MONITOR)
        assert x == 1600 + 20 - PANEL[0]

    def test_stays_on_screen(self) -> None:
        x, _ = place_panel(TOP_BAR_ICON, *PANEL, MONITOR)
        assert x == TOP_BAR_ICON.x + TOP_BAR_ICON.width - PANEL[0]
        assert x + PANEL[0] <= MONITOR.width

    def test_keeps_a_margin_at_the_right_edge(self) -> None:
        """dwm's tray can sit flush against the screen edge, and right-aligning
        with it would put the panel's edge there too."""
        x, _ = place_panel(Rect(1900, 0, 20, 20), *PANEL, MONITOR)
        assert x == MONITOR.width - PANEL[0] - EDGE

    def test_clamps_at_the_left_edge(self) -> None:
        x, _ = place_panel(Rect(0, 0, 20, 20), *PANEL, MONITOR)
        assert x == EDGE


class TestBottomBar:
    def test_flips_above_the_anchor(self) -> None:
        """Below a bottom bar there is no room, so the panel goes above it."""
        anchor = Rect(1880, 1060, 20, 20)
        _, y = place_panel(anchor, *PANEL, MONITOR)
        assert y == anchor.y - PANEL[1] - GAP

    def test_stays_on_screen_when_the_panel_is_taller_than_the_screen(self) -> None:
        anchor = Rect(1880, 1060, 20, 20)
        _, y = place_panel(anchor, 240, 2000, MONITOR)
        assert y == MONITOR.y + EDGE


class TestSecondMonitor:
    """A monitor to the right of the origin: clamping must use its own bounds,
    not the panel's distance from (0, 0)."""

    RIGHT = Rect(1920, 0, 2560, 1440)

    def test_places_within_that_monitor(self) -> None:
        x, y = place_panel(Rect(4440, 0, 20, 20), *PANEL, self.RIGHT)
        assert x == 4440 + 20 - PANEL[0]
        assert self.RIGHT.x <= x
        assert x + PANEL[0] <= self.RIGHT.x + self.RIGHT.width
        assert y == 20 + GAP

    def test_keeps_a_margin_at_that_monitors_right_edge(self) -> None:
        """The clamp bound is the monitor's own right edge, not the width of
        the desktop -- 4480 here, not 2560."""
        x, _ = place_panel(Rect(4460, 0, 20, 20), *PANEL, self.RIGHT)
        assert x == self.RIGHT.x + self.RIGHT.width - PANEL[0] - EDGE

    def test_does_not_drift_onto_the_left_monitor(self) -> None:
        x, _ = place_panel(Rect(1920, 0, 20, 20), *PANEL, self.RIGHT)
        assert x >= self.RIGHT.x


class TestNoMonitor:
    def test_returns_the_unclamped_position(self) -> None:
        """Better an off-screen panel that can be diagnosed than one silently
        dragged onto a guessed display."""
        x, y = place_panel(TOP_BAR_ICON, *PANEL)
        assert (x, y) == (TOP_BAR_ICON.x + TOP_BAR_ICON.width - PANEL[0], 20 + GAP)
