"""Abstract display-backend interface.

Every backend must be able to:
  1. Read the current topology (what is connected, in what mode).
  2. Apply a set of output configuration changes.
  3. Verify that the changes took effect.
"""

from __future__ import annotations

import abc

from ..types import OutputConfig, Topology


class DisplayBackend(abc.ABC):
    @abc.abstractmethod
    async def get_topology(self) -> Topology:
        """Read the current display topology from the display server."""

    @abc.abstractmethod
    async def apply(self, changes: list[tuple[str, OutputConfig]]) -> bool:
        """Apply configuration changes.  Returns True on apparent success."""

    @abc.abstractmethod
    async def verify(self, changes: list[tuple[str, OutputConfig]]) -> bool:
        """Re-read state and confirm the changes are in effect."""

    async def cleanup_stale(self) -> list[str]:
        """Turn off ghost outputs (disconnected but still driven by a CRTC).

        A ghost CRTC can keep a Type-C PHY occupied, which blocks the PD
        firmware from renegotiating DisplayPort alt mode when the monitor is
        replugged -- so ghosts must be cleaned even when no profile apply is
        pending.  Returns the connector names that were turned off.
        """
        return []

    @abc.abstractmethod
    def session_type(self) -> str:
        """Human-readable session identifier (e.g. 'x11', 'gnome-wayland')."""
