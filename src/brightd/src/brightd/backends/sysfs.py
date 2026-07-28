"""Kernel backlight backend for the internal panel.

Writes go to ``brightness`` through a single long-lived ``O_WRONLY`` file
descriptor -- measured at ~70 us with no kernel-side rate limiting, so a 60 Hz
slider drag costs about 0.4% of one core and needs no coalescing at all.

``brightness`` is also the value to *read*.  ``actual_brightness`` is a
quantised hardware readback that lands one LSB low for roughly 6% of values on
this panel, so displaying it produces a slider that visibly jitters.  Its one
job is to be a ``poll(POLLPRI)`` wakeup source, which is how brightd notices
brightness changed by a hotkey or another tool.

``bl_power`` is never touched: it is root-only here, and writing 4
(``FB_BLANK_POWERDOWN``) blanks the panel.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..curve import Curve, LStarCurve, clamp, percent_to_raw, raw_to_percent
from ..types import BacklightError, DisplayInfo, DisplayKind
from .base import Backlight

log = logging.getLogger(__name__)

BACKLIGHT_ROOT = Path("/sys/class/backlight")

DEFAULT_MIN_FRACTION = 0.01
"""Floor as a fraction of max, so 0% is "dimmest safe" rather than black.

The kernel accepts a raw 0 and blacks the panel out completely, and on this
laptop the brightness hotkeys are dead (``xbacklight`` is a no-op on modern
i915), so a user who blacks out the screen has no recovery short of a TTY.
"""

# raw is the driver's own register; firmware/platform go through ACPI and are
# coarser and less reliable, so prefer them only as fallbacks.
_TYPE_RANK = {"raw": 0, "firmware": 1, "platform": 2}
_INTERNAL_PREFIXES = ("eDP", "LVDS", "DSI")


@dataclass(frozen=True)
class BacklightDevice:
    """One entry under /sys/class/backlight."""

    path: Path
    name: str
    max_raw: int
    device_type: str
    connector: str

    @property
    def is_internal(self) -> bool:
        return self.connector.startswith(_INTERNAL_PREFIXES)


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _connector_of(device_dir: Path) -> str:
    """DRM connector driving this backlight, e.g. ``eDP-1``.

    The ``device`` symlink resolves into the connector directory
    (``.../drm/card2/card2-eDP-1/intel_backlight``), which is a far stronger
    signal than the ``type`` attribute for deciding what a backlight belongs to.
    """
    try:
        parent = device_dir.resolve().parent.name
    except OSError:
        return ""
    _, _, connector = parent.partition("-")
    return connector


def discover_devices(root: Path = BACKLIGHT_ROOT) -> list[BacklightDevice]:
    """Enumerate backlight devices, best candidate first."""
    if not root.is_dir():
        return []

    devices: list[BacklightDevice] = []
    for entry in sorted(root.iterdir()):
        max_raw = _read_int(entry / "max_brightness")
        if max_raw is None or max_raw <= 0:
            continue  # a device we could only ever set to zero
        try:
            device_type = (entry / "type").read_text().strip()
        except OSError:
            device_type = "unknown"
        devices.append(
            BacklightDevice(
                path=entry,
                name=entry.name,
                max_raw=max_raw,
                device_type=device_type,
                connector=_connector_of(entry),
            )
        )

    devices.sort(
        key=lambda d: (
            not d.is_internal,
            _TYPE_RANK.get(d.device_type, len(_TYPE_RANK)),
            -d.max_raw,
            d.name,
        )
    )
    return devices


class SysfsBacklight(Backlight):
    """Brightness for a panel with a kernel backlight device."""

    # Writes are ~70 us and unthrottled by the kernel, so never delay them:
    # any debounce here is a slider that visibly lags the finger for no gain.
    min_period = 0.0
    debounce = 0.0

    def __init__(
        self,
        device: BacklightDevice,
        *,
        min_fraction: float = DEFAULT_MIN_FRACTION,
        curve: Curve | None = None,
        label: str = "Built-in display",
    ) -> None:
        self._device = device
        self._curve: Curve = curve if curve is not None else LStarCurve()
        self._min_raw = max(1, round(device.max_raw * clamp(min_fraction, 0.0, 1.0)))
        self._fd: int | None = None
        self._last_written_raw: int | None = None
        self._info = DisplayInfo(
            id=device.connector or device.name,
            label=label,
            kind=DisplayKind.INTERNAL,
        )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def info(self) -> DisplayInfo:
        return self._info

    @property
    def device(self) -> BacklightDevice:
        return self._device

    @property
    def min_raw(self) -> int:
        return self._min_raw

    @property
    def max_raw(self) -> int:
        return self._device.max_raw

    @property
    def last_written_raw(self) -> int | None:
        return self._last_written_raw

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def read_raw(self) -> int:
        value = _read_int(self._device.path / "brightness")
        if value is None:
            raise BacklightError(f"Cannot read brightness of {self._device.name}")
        return value

    def read_percent(self) -> float:
        return raw_to_percent(self.read_raw(), self._min_raw, self.max_raw, self._curve)

    def percent_of(self, raw: int) -> float:
        """Convert a raw value to a percentage using this device's curve."""
        return raw_to_percent(raw, self._min_raw, self.max_raw, self._curve)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def write_percent(self, percent: float) -> None:
        self.write_raw(percent_to_raw(percent, self._min_raw, self.max_raw, self._curve))

    def write_raw(self, raw: int) -> None:
        """Set the raw register, trying each write mechanism in turn."""
        raw = int(clamp(float(raw), float(self._min_raw), float(self.max_raw)))
        self._last_written_raw = raw
        errors: list[str] = []
        for attempt in (self._write_direct, self._write_brightnessctl, self._write_logind):
            try:
                attempt(raw)
                return
            except (OSError, BacklightError) as exc:
                errors.append(f"{attempt.__name__}: {exc}")
        raise BacklightError(
            f"All write paths failed for {self._device.name}: {'; '.join(errors)}"
        )

    def _ensure_fd(self) -> int:
        if self._fd is None:
            self._fd = os.open(self._device.path / "brightness", os.O_WRONLY)
        return self._fd

    def _write_direct(self, raw: int) -> None:
        """Write through the persistent fd, reopening once if it went stale.

        A udev re-add re-applies the group permission and can invalidate the
        descriptor, so one reopen-and-retry is worth it before falling through
        to the slower mechanisms.
        """
        try:
            self._write_fd(raw)
        except OSError as exc:
            log.debug("Direct write failed (%s); reopening fd", exc)
            self._close_fd()
            self._write_fd(raw)

    def _write_fd(self, raw: int) -> None:
        fd = self._ensure_fd()
        payload = str(raw).encode("ascii")
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, payload)
        # sysfs treats each write as one complete command and ignores the file
        # length, but a regular file keeps the tail of a longer previous value
        # -- 19200 followed by 500 would read back as 50000.  Truncating is a
        # verified no-op on sysfs and makes the two behave identically, which
        # is what lets the tests exercise this path for real.
        try:
            os.ftruncate(fd, len(payload))
        except OSError:
            pass

    def _write_brightnessctl(self, raw: int) -> None:
        binary = shutil.which("brightnessctl")
        if binary is None:
            raise BacklightError("brightnessctl not installed")
        result = subprocess.run(
            [binary, "-q", "-c", "backlight", "-d", self._device.name, "set", str(raw)],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        if result.returncode != 0:
            raise BacklightError(result.stderr.strip() or "brightnessctl failed")

    def _write_logind(self, raw: int) -> None:
        """Ask logind to do it.

        The only mechanism that survives the udev rule being absent, since it
        is gated on owning the active session rather than on file permissions.
        Gio is imported lazily so ``brightd-ctl`` stays free of GObject unless
        it actually needs this path.
        """
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        try:
            bus.call_sync(
                "org.freedesktop.login1",
                "/org/freedesktop/login1/session/auto",
                "org.freedesktop.login1.Session",
                "SetBrightness",
                GLib.Variant("(ssu)", ("backlight", self._device.name, raw)),
                None,
                Gio.DBusCallFlags.NONE,
                5000,
                None,
            )
        except GLib.Error as exc:
            raise BacklightError(f"logind SetBrightness: {exc.message}") from exc

    # ------------------------------------------------------------------
    # External-change notification
    # ------------------------------------------------------------------

    def open_change_watch(self) -> int:
        """Return a primed fd that becomes ready when brightness changes.

        ``poll(POLLPRI)`` fires only on ``actual_brightness`` -- watching
        ``brightness`` or ``bl_power`` never wakes up at all.  The descriptor
        must be read once before it is polled, or ``poll()`` returns
        immediately forever and spins a core.
        """
        fd = os.open(self._device.path / "actual_brightness", os.O_RDONLY)
        os.read(fd, 64)
        return fd

    @staticmethod
    def drain_change_watch(fd: int) -> None:
        """Re-arm the watch descriptor after a wakeup.

        Seeking back and reading to EOF is mandatory: skip it and ``poll()``
        reports ready forever.
        """
        os.lseek(fd, 0, os.SEEK_SET)
        os.read(fd, 64)

    def is_own_echo(self, raw: int, tolerance: int = 2) -> bool:
        """True if ``raw`` looks like the readback of our own last write.

        Compared with a tolerance rather than for equality because
        ``actual_brightness`` quantises, and notifications also fire for
        redundant same-value writes -- so "the value did not change" is not a
        usable suppression test.
        """
        if self._last_written_raw is None:
            return False
        return abs(raw - self._last_written_raw) <= tolerance

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def _close_fd(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def close(self) -> None:
        self._close_fd()
