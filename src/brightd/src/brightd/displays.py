"""Assembling the set of controllable displays.

Shared by the daemon and by ``brightd-ctl`` so both agree on which device is
"the" internal panel and how percentages map onto it.  Imports no GTK.

External-monitor support is probed lazily and degrades quietly: if ``ddcutil``
is missing or ``/dev/i2c-*`` is inaccessible, the internal panel still works
perfectly and the reason is reported rather than swallowed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .backends.base import Backlight
from .backends.ddc import build_external_backlights, ddc_availability
from .backends.discovery import DRM_ROOT
from .backends.sysfs import (
    BACKLIGHT_ROOT,
    DEFAULT_MIN_FRACTION,
    SysfsBacklight,
    discover_devices,
)
from .types import BacklightUnavailable, DdcAvailability

log = logging.getLogger(__name__)


def internal_backlight(
    *,
    min_fraction: float = DEFAULT_MIN_FRACTION,
    device_name: str | None = None,
    root: Path = BACKLIGHT_ROOT,
) -> SysfsBacklight | None:
    """The built-in panel's backlight, or ``None`` if the machine has none."""
    devices = discover_devices(root)
    if not devices:
        return None
    if device_name is not None:
        for device in devices:
            if device.name == device_name:
                return SysfsBacklight(device, min_fraction=min_fraction)
        log.warning("Backlight device %r not found; using %s", device_name, devices[0].name)
    return SysfsBacklight(devices[0], min_fraction=min_fraction)


def external_backlights(
    *, drm_root: Path = DRM_ROOT
) -> tuple[list[Backlight], DdcAvailability]:
    """External monitors reachable over DDC/CI, plus why there might be none."""
    availability = ddc_availability(drm_root)
    if availability is not DdcAvailability.OK:
        log.info("DDC/CI: %s", availability.message)
        return [], availability
    try:
        return list(build_external_backlights(drm_root)), availability
    except BacklightUnavailable as exc:
        log.info("DDC/CI unavailable: %s", exc)
        return [], availability


def build_backlights(
    *,
    min_fraction: float = DEFAULT_MIN_FRACTION,
    device_name: str | None = None,
    enable_ddc: bool = True,
    backlight_root: Path = BACKLIGHT_ROOT,
    drm_root: Path = DRM_ROOT,
) -> tuple[list[Backlight], DdcAvailability]:
    """Every display brightd can drive, internal panel first."""
    backlights: list[Backlight] = []
    internal = internal_backlight(
        min_fraction=min_fraction, device_name=device_name, root=backlight_root
    )
    if internal is not None:
        backlights.append(internal)

    if not enable_ddc:
        return backlights, DdcAvailability.NO_DDCUTIL
    external, availability = external_backlights(drm_root=drm_root)
    backlights.extend(external)
    return backlights, availability
