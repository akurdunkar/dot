"""Connector discovery straight from sysfs.

``ddcutil detect`` takes seconds and renumbers displays on every hotplug, so it
is unusable both as a hot path and as an addressing scheme.  Everything needed
is already in ``/sys/class/drm``: each connector directory carries its
connection ``status``, an ``edid`` blob, a ``ddc`` symlink naming the I2C bus,
and -- for the internal panel -- a ``*_backlight`` subdirectory.

That gives a privilege-free, race-free connector -> bus -> identity map in
about a millisecond, which is what lets brightd address ddcutil by the stable
``--bus N`` instead of the volatile ``--display N``.

The root path is injectable so the whole module is testable against a fake
sysfs tree.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..edid import parse_edid
from ..types import MonitorIdentity

log = logging.getLogger(__name__)

DRM_ROOT = Path("/sys/class/drm")

# Connector dirs are "<card>-<connector>", e.g. "card2-eDP-1" -> "eDP-1".
_CONNECTOR_DIR = re.compile(r"^card\d+-(?P<connector>.+)$")
_I2C_BUS = re.compile(r"^i2c-(?P<bus>\d+)$")

# Connector name prefixes that are physically internal panels.  These are
# always driven through the kernel backlight, never DDC -- an eDP connector
# does expose a working I2C bus and a valid EDID, so ddcutil will happily scan
# it and would fight systemd-backlight for control of the same panel.
_INTERNAL_PREFIXES = ("eDP", "LVDS", "DSI")


@dataclass(frozen=True)
class Connector:
    """A DRM connector and everything brightd needs to know about it."""

    name: str
    status: str
    bus: int | None
    identity: MonitorIdentity | None
    has_backlight: bool

    @property
    def connected(self) -> bool:
        return self.status == "connected"

    @property
    def is_internal(self) -> bool:
        """True for a built-in panel.

        Checked two ways because either signal alone can mislead: a docking
        station can present a connector whose name looks external, and a
        connector's backlight subdirectory is the authoritative statement that
        the kernel owns its brightness.
        """
        if self.has_backlight:
            return True
        return self.name.startswith(_INTERNAL_PREFIXES)

    @property
    def label(self) -> str:
        if self.identity is not None:
            return self.identity.label
        return self.name


def _read_bus(connector_dir: Path) -> int | None:
    """I2C bus number from the ``ddc`` symlink, if the connector has one."""
    ddc = connector_dir / "ddc"
    if not ddc.exists():
        return None
    match = _I2C_BUS.match(ddc.resolve().name)
    return int(match.group("bus")) if match else None


def _read_identity(connector_dir: Path) -> MonitorIdentity | None:
    edid = connector_dir / "edid"
    try:
        data = edid.read_bytes()
    except OSError:
        return None
    # A disconnected connector keeps a zero-length edid file.
    return parse_edid(data) if data else None


def _has_backlight(connector_dir: Path) -> bool:
    return any(child.name.endswith("_backlight") for child in connector_dir.iterdir())


def scan_connectors(drm_root: Path = DRM_ROOT) -> list[Connector]:
    """Enumerate DRM connectors.  Never raises; unreadable entries are skipped."""
    if not drm_root.is_dir():
        log.debug("No DRM root at %s", drm_root)
        return []

    connectors: list[Connector] = []
    for entry in sorted(drm_root.iterdir()):
        match = _CONNECTOR_DIR.match(entry.name)
        if match is None or not entry.is_dir():
            continue
        try:
            status = (entry / "status").read_text().strip()
        except OSError:
            continue  # not a connector directory after all
        try:
            has_backlight = _has_backlight(entry)
        except OSError:
            has_backlight = False
        connectors.append(
            Connector(
                name=match.group("connector"),
                status=status,
                bus=_read_bus(entry),
                identity=_read_identity(entry),
                has_backlight=has_backlight,
            )
        )
    return connectors


def external_connectors(drm_root: Path = DRM_ROOT) -> list[Connector]:
    """Connected, non-internal connectors that expose an I2C bus."""
    return [
        connector
        for connector in scan_connectors(drm_root)
        if connector.connected and not connector.is_internal and connector.bus is not None
    ]
