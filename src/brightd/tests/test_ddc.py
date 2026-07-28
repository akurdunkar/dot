"""The DDC/CI backend, with ddcutil replaced by an injected fake runner.

No ddcutil, no I2C bus and no external monitor are needed to run these -- which
matters, because the machine this was written on has none of the three.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

from brightd.backends.ddc import (
    CommandResult,
    DdcBacklight,
    build_external_backlights,
    parse_getvcp_brief,
)
from brightd.types import BacklightError, DisplayInfo, DisplayKind


class FakeRunner:
    """Stands in for ddcutil, recording every argv it is handed."""

    def __init__(self, stdout: str = "VCP 10 C 50 100", returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str], timeout: float) -> CommandResult:
        self.calls.append(list(argv))
        return CommandResult(self.returncode, self.stdout, self.stderr)


def make_backlight(runner: FakeRunner, bus: int = 16) -> DdcBacklight:
    info = DisplayInfo(id="DP-1", label="DELL U2720Q", kind=DisplayKind.EXTERNAL)
    return DdcBacklight(info, bus, runner=runner)


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------


def test_parses_the_terse_getvcp_form() -> None:
    assert parse_getvcp_brief("VCP 10 C 50 100") == (50, 100)


def test_parses_with_surrounding_noise() -> None:
    assert parse_getvcp_brief("some warning\nVCP 10 C 75 100\n") == (75, 100)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "VCP 10 C",
        "VCP 12 C 50 100",  # a different feature
        "Display not found",
        "VCP 10 C x y",
    ],
)
def test_rejects_unparseable_output(text: str) -> None:
    with pytest.raises(BacklightError):
        parse_getvcp_brief(text)


# ----------------------------------------------------------------------
# Reading and writing
# ----------------------------------------------------------------------


def test_reads_brightness_as_a_percentage() -> None:
    runner = FakeRunner("VCP 10 C 50 100")
    assert make_backlight(runner).read_percent() == pytest.approx(50.0)


def test_scales_a_non_standard_maximum() -> None:
    """Monitors are not required to use 0-100."""
    runner = FakeRunner("VCP 10 C 40 80")
    assert make_backlight(runner).read_percent() == pytest.approx(50.0)


def test_addresses_the_bus_and_skips_verification() -> None:
    runner = FakeRunner()
    make_backlight(runner, bus=16).read_percent()
    argv = runner.calls[0]
    assert argv[0] == "ddcutil"
    assert "--bus" in argv and argv[argv.index("--bus") + 1] == "16"
    assert "--noverify" in argv  # the single biggest latency win
    assert "--display" not in argv  # display numbers are not stable
    assert argv[-3:] == ["getvcp", "10", "--brief"]


def test_write_probes_the_range_once_then_reuses_it() -> None:
    runner = FakeRunner()
    backlight = make_backlight(runner)
    backlight.write_percent(75.0)
    backlight.write_percent(25.0)

    verbs = [argv[argv.index("--sleep-multiplier") + 2] for argv in runner.calls]
    assert verbs == ["getvcp", "setvcp", "setvcp"], "the range must be probed only once"
    assert runner.calls[1][-2:] == ["10", "75"]
    assert runner.calls[2][-2:] == ["10", "25"]


def test_write_uses_the_learned_maximum() -> None:
    runner = FakeRunner("VCP 10 C 40 80")
    backlight = make_backlight(runner)
    backlight.write_percent(50.0)
    assert runner.calls[-1][-1] == "40"


def test_a_failing_command_raises() -> None:
    runner = FakeRunner(returncode=1, stderr="DDC communication failed")
    with pytest.raises(BacklightError, match="DDC communication failed"):
        make_backlight(runner).read_percent()


# ----------------------------------------------------------------------
# Assembly
# ----------------------------------------------------------------------


def _ddcutil_missing(_name: str) -> str | None:
    return None


def _ddcutil_present(_name: str) -> str | None:
    return "/usr/bin/ddcutil"


def _i2c_accessible(_path: str, _mode: int) -> bool:
    return True


def test_no_ddcutil_means_no_external_backlights(drm_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The common case on this machine: it must degrade, not explode."""
    monkeypatch.setattr("brightd.backends.ddc.shutil.which", _ddcutil_missing)
    from brightd.displays import external_backlights
    from brightd.types import DdcAvailability

    backlights, availability = external_backlights(drm_root=drm_root)
    assert backlights == []
    assert availability is DdcAvailability.NO_DDCUTIL
    assert "ddcutil" in availability.message


def test_builds_one_backlight_per_external_monitor(
    drm_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("brightd.backends.ddc.shutil.which", _ddcutil_present)
    monkeypatch.setattr("brightd.backends.ddc.os.access", _i2c_accessible)

    backlights = build_external_backlights(drm_root, runner=FakeRunner())
    assert [b.info.id for b in backlights] == ["DP-1"]
    assert backlights[0].bus == 16
    assert backlights[0].info.kind is DisplayKind.EXTERNAL
    assert backlights[0].info.label == "U2720Q"


def test_ddc_is_slower_than_sysfs_and_says_so() -> None:
    """The throttle policy is what stops a drag wedging a monitor's DDC engine."""
    backlight = make_backlight(FakeRunner())
    assert backlight.min_period > 0.0
    assert backlight.debounce > 0.0
