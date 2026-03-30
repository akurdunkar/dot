"""Backend detection and registration."""

from __future__ import annotations

import logging
import os

from .base import DisplayBackend

log = logging.getLogger(__name__)

__all__ = ["DisplayBackend", "detect_backend"]


def detect_backend() -> DisplayBackend:
    """Auto-detect the appropriate display backend for the active session.

    Currently only the X11/XRandR backend is implemented.  The detection
    scaffold is kept so that Wayland backends can be added later.
    """
    xdg_session = os.environ.get("XDG_SESSION_TYPE", "")
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "")
    x_display = os.environ.get("DISPLAY", "")

    if wayland_display or xdg_session == "wayland":
        raise NotImplementedError(
            "No Wayland backend is available yet. "
            "Contributions for GNOME/Mutter or wlroots support welcome."
        )

    if x_display or xdg_session == "x11":
        log.info("Detected X11 session (DISPLAY=%s)", x_display)
        from .xrandr import XrandrBackend

        return XrandrBackend()

    log.warning("No graphical session detected, falling back to X11/XRandR")
    from .xrandr import XrandrBackend

    return XrandrBackend()
