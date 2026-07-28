"""Core data types for brightd."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class DisplayKind(Enum):
    """How a display's brightness is reached."""

    INTERNAL = auto()
    """A panel with a kernel backlight device under /sys/class/backlight."""

    EXTERNAL = auto()
    """A monitor driven over DDC/CI (VCP feature 0x10)."""


@dataclass(frozen=True)
class MonitorIdentity:
    """Stable monitor identity derived from EDID data.

    Deliberately mirrors displayd's ``MonitorIdentity`` so the two projects
    describe the same hardware the same way, but is *copied* rather than
    imported -- brightd is its own distribution and must not grow a hard
    runtime dependency on displayd.
    """

    manufacturer: str
    model: str
    serial: str
    name: str = ""

    @property
    def stable_id(self) -> str:
        return f"{self.manufacturer}/{self.model}/{self.serial}"

    @property
    def label(self) -> str:
        """Human-facing name for the tray menu and slider rows."""
        if self.name:
            return self.name
        if self.model:
            return f"{self.manufacturer} {self.model}".strip()
        return self.stable_id


UNKNOWN_IDENTITY = MonitorIdentity("???", "???", "")


@dataclass(frozen=True)
class DisplayInfo:
    """A display brightd can control."""

    id: str
    """Stable key. The DRM connector name (``eDP-1``, ``DP-2``)."""

    label: str
    """Human-facing name shown next to the slider."""

    kind: DisplayKind


class DdcAvailability(Enum):
    """Why external-monitor control is or is not usable.

    Kept distinct so the UI can tell "you have no external monitors" apart from
    "ddcutil is not installed" apart from "you lack permission on /dev/i2c-*".
    Collapsing these into a single "DDC unavailable" makes a fixable setup
    problem look like a broken app.
    """

    OK = auto()
    NO_DDCUTIL = auto()
    NO_PERMISSION = auto()
    NO_EXTERNAL_DISPLAYS = auto()

    @property
    def message(self) -> str:
        return _DDC_MESSAGES[self]


_DDC_MESSAGES: dict[DdcAvailability, str] = {
    DdcAvailability.OK: "External monitor control available",
    DdcAvailability.NO_DDCUTIL: "ddcutil not installed — external monitors unavailable",
    DdcAvailability.NO_PERMISSION: "No access to /dev/i2c-* — see README (log out and back in after setup)",
    DdcAvailability.NO_EXTERNAL_DISPLAYS: "No external monitors connected",
}


class BacklightError(RuntimeError):
    """A brightness read or write failed."""


class BacklightUnavailable(BacklightError):
    """The device exists but cannot be driven (missing tool, no permission)."""
