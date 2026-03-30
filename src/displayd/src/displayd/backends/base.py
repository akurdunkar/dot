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

    @abc.abstractmethod
    def session_type(self) -> str:
        """Human-readable session identifier (e.g. 'x11', 'gnome-wayland')."""
