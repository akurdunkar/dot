"""Backend detection and registration."""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from ..topology import read_lid_state
from ..types import OutputConfig, Topology
from .base import DisplayBackend

log = logging.getLogger(__name__)

__all__ = ["DisplayBackend", "LidAwareBackend", "detect_backend"]


class LidAwareBackend(DisplayBackend):
    """Delegates to a real backend, stamping the current lid state onto every
    topology so closed-lid setups hash as a distinct topology.

    Every component that computes topology hashes (daemon, editor, ctl) must
    go through this wrapper so saved profiles and live matching agree."""

    def __init__(
        self,
        inner: DisplayBackend,
        lid_state: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._inner = inner
        self._lid_state = lid_state if lid_state is not None else read_lid_state

    async def get_topology(self) -> Topology:
        topo = await self._inner.get_topology()
        return Topology(outputs=topo.outputs, lid_closed=self._lid_state())

    async def apply(self, changes: list[tuple[str, OutputConfig]]) -> bool:
        return await self._inner.apply(changes)

    async def verify(self, changes: list[tuple[str, OutputConfig]]) -> bool:
        return await self._inner.verify(changes)

    def session_type(self) -> str:
        return self._inner.session_type()


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
