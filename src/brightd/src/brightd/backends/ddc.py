"""DDC/CI backend for external monitors, driven through ``ddcutil``.

Shelling out beats the alternatives here: ``ddcutil-service`` is not packaged
on this distribution, ``monitorcontrol`` drags in pyudev for weaker timing
logic, and ``libddcutil`` via ctypes means a large hand-written struct surface
against a soname that differs between the distro package and upstream.  A
subprocess is zero-dependency, trivially typed, and testable by injecting a
fake runner.

Monitors are addressed by ``--bus N`` from :mod:`.discovery`, never by
``--display N``: ddcutil renumbers displays on every hotplug, so a display
number captured at startup can silently point at a different monitor later.

Two flags matter for interactivity.  ``--noverify`` suppresses the read-back
that ``setvcp`` otherwise performs, roughly halving write latency, and
``--sleep-multiplier`` shortens the conservative inter-operation delays.  Even
so a write costs 200-350 ms, which is why this backend declares a real
debounce and rate cap for the writer to honour.

DDC is not concurrency-safe on a bus: parallel conversations interleave and
produce spurious I/O errors, so all traffic for a bus is serialised.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from ..curve import LinearCurve, percent_to_raw, raw_to_percent
from ..types import (
    BacklightError,
    BacklightUnavailable,
    DdcAvailability,
    DisplayInfo,
    DisplayKind,
)
from .base import Backlight
from .discovery import DRM_ROOT, Connector, external_connectors

log = logging.getLogger(__name__)

DDCUTIL = "ddcutil"
VCP_BRIGHTNESS = "10"

_SLEEP_MULTIPLIER = "0.4"
_DEFAULT_TIMEOUT = 10.0

# One lock per I2C bus, shared across every DdcBacklight instance -- two
# objects can legitimately address the same bus while a hotplug is settling.
_BUS_LOCKS: dict[int, threading.Lock] = {}
_BUS_LOCKS_GUARD = threading.Lock()


def bus_lock(bus: int) -> threading.Lock:
    """The process-wide lock serialising DDC traffic on ``bus``."""
    with _BUS_LOCKS_GUARD:
        return _BUS_LOCKS.setdefault(bus, threading.Lock())


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    """Runs a command.  Injected so tests never fork anything."""

    def __call__(self, argv: Sequence[str], timeout: float) -> CommandResult: ...


def run_subprocess(argv: Sequence[str], timeout: float) -> CommandResult:
    try:
        completed = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise BacklightError(f"{argv[0]} timed out after {timeout:g}s") from exc
    except OSError as exc:
        raise BacklightError(f"Cannot run {argv[0]}: {exc}") from exc
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def parse_getvcp_brief(text: str) -> tuple[int, int]:
    """Parse ``ddcutil getvcp 10 --brief`` output.

    The terse form is a single line of whitespace-separated fields::

        VCP 10 C 50 100
              ^ ^  ^-- maximum
              | +----- current value
              +------- C = continuous

    Anything else -- an error string, a feature the monitor reports as
    unsupported, an empty response -- raises rather than guessing.
    """
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[0] == "VCP" and fields[1].upper() == VCP_BRIGHTNESS:
            try:
                return int(fields[3]), int(fields[4])
            except ValueError:
                break
    raise BacklightError(f"Unparseable getvcp output: {text.strip()!r}")


def ddc_availability(drm_root: Path = DRM_ROOT) -> DdcAvailability:
    """Why external-monitor control is or is not usable right now.

    Ordered so the message names the thing the user would fix first.
    """
    if shutil.which(DDCUTIL) is None:
        return DdcAvailability.NO_DDCUTIL
    connectors = external_connectors(drm_root)
    if not connectors:
        return DdcAvailability.NO_EXTERNAL_DISPLAYS
    for connector in connectors:
        if connector.bus is not None and os.access(f"/dev/i2c-{connector.bus}", os.R_OK | os.W_OK):
            return DdcAvailability.OK
    return DdcAvailability.NO_PERMISSION


class DdcBacklight(Backlight):
    """Brightness of one external monitor over DDC/CI."""

    # A write is a 200-350 ms fork, and sustained sub-100 ms hammering can wedge
    # a monitor's DDC engine outright, so gate both the gesture start and the
    # sustained rate.
    min_period = 0.20
    debounce = 0.12

    def __init__(
        self,
        info: DisplayInfo,
        bus: int,
        *,
        runner: CommandRunner | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._info = info
        self._bus = bus
        self._run: CommandRunner = runner if runner is not None else run_subprocess
        self._timeout = timeout
        self._curve = LinearCurve()
        self._max_value: int | None = None

    @property
    def info(self) -> DisplayInfo:
        return self._info

    @property
    def bus(self) -> int:
        return self._bus

    def _argv(self, *args: str) -> list[str]:
        return [
            DDCUTIL,
            "--bus",
            str(self._bus),
            "--noverify",
            "--sleep-multiplier",
            _SLEEP_MULTIPLIER,
            *args,
        ]

    def _invoke(self, *args: str) -> CommandResult:
        with bus_lock(self._bus):
            result = self._run(self._argv(*args), self._timeout)
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip() or "unknown error"
            raise BacklightError(f"ddcutil bus {self._bus}: {message}")
        return result

    def read_raw(self) -> tuple[int, int]:
        """Current and maximum VCP 0x10 values."""
        result = self._invoke("getvcp", VCP_BRIGHTNESS, "--brief")
        current, maximum = parse_getvcp_brief(result.stdout)
        self._max_value = maximum
        return current, maximum

    def read_percent(self) -> float:
        current, maximum = self.read_raw()
        return raw_to_percent(current, 0, maximum, self._curve)

    def write_percent(self, percent: float) -> None:
        maximum = self._max_value
        if maximum is None:
            # First write of the session: one probe establishes the range, and
            # every later write reuses it.  Monitors are not required to use
            # 0-100, and writing past the maximum is simply rejected.
            _, maximum = self.read_raw()
        value = percent_to_raw(percent, 0, maximum, self._curve)
        self._invoke("setvcp", VCP_BRIGHTNESS, str(value))


def build_external_backlights(
    drm_root: Path = DRM_ROOT,
    *,
    runner: CommandRunner | None = None,
) -> list[DdcBacklight]:
    """One backlight per connected external monitor.

    Raises :class:`BacklightUnavailable` when DDC cannot work at all, so the
    caller can show the specific reason instead of an empty list.
    """
    availability = ddc_availability(drm_root)
    if availability is DdcAvailability.NO_DDCUTIL:
        raise BacklightUnavailable(availability.message)
    if availability is DdcAvailability.NO_PERMISSION:
        raise BacklightUnavailable(availability.message)

    backlights: list[DdcBacklight] = []
    for connector in external_connectors(drm_root):
        assert connector.bus is not None  # external_connectors() filters these out
        backlights.append(
            DdcBacklight(
                DisplayInfo(
                    id=connector.name,
                    label=_disambiguated_label(connector),
                    kind=DisplayKind.EXTERNAL,
                ),
                connector.bus,
                runner=runner,
            )
        )
    return backlights


def _disambiguated_label(connector: Connector) -> str:
    """Label a monitor, keeping the connector name when EDID cannot identify it.

    Two identical monitors of a model that ships no serial number produce the
    same EDID identity, so the connector name is appended to keep the rows
    distinguishable and the ids unique.
    """
    identity = connector.identity
    if identity is None:
        return connector.name
    if identity.serial:
        return identity.label
    return f"{identity.label} ({connector.name})"
