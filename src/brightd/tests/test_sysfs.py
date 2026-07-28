"""The kernel backlight backend, exercised against a fake sysfs tree."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from brightd.backends.sysfs import SysfsBacklight, discover_devices
from brightd.types import BacklightError, DisplayKind


def make_backlight(root: Path, **kwargs: float) -> SysfsBacklight:
    devices = discover_devices(root)
    assert devices, "fixture should provide one backlight device"
    return SysfsBacklight(devices[0], **kwargs)  # type: ignore[arg-type]


def test_discovers_the_device_and_its_connector(backlight_root: Path) -> None:
    devices = discover_devices(backlight_root)
    assert len(devices) == 1
    device = devices[0]
    assert device.name == "intel_backlight"
    assert device.max_raw == 192000
    assert device.device_type == "raw"
    assert device.connector == "eDP-1"
    assert device.is_internal


def test_missing_root_is_not_an_error(tmp_path: Path) -> None:
    assert discover_devices(tmp_path / "nope") == []


def test_device_with_zero_maximum_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / "backlight"
    (root / "broken").mkdir(parents=True)
    (root / "broken" / "max_brightness").write_text("0\n")
    assert discover_devices(root) == []


def test_reads_current_value(backlight_root: Path) -> None:
    backlight = make_backlight(backlight_root)
    assert backlight.read_raw() == 19200
    assert backlight.info.id == "eDP-1"
    assert backlight.info.kind is DisplayKind.INTERNAL
    backlight.close()


def test_minimum_is_one_percent_of_maximum(backlight_root: Path) -> None:
    backlight = make_backlight(backlight_root)
    assert backlight.min_raw == 1920
    assert backlight.max_raw == 192000
    backlight.close()


def test_zero_percent_never_blacks_the_panel(backlight_root: Path) -> None:
    backlight = make_backlight(backlight_root)
    backlight.write_percent(0.0)
    assert backlight.read_raw() == backlight.min_raw > 0
    backlight.close()


def test_writes_round_trip(backlight_root: Path) -> None:
    backlight = make_backlight(backlight_root)
    backlight.write_percent(100.0)
    assert backlight.read_raw() == 192000
    assert backlight.read_percent() == pytest.approx(100.0, abs=0.5)
    backlight.close()


def test_a_shorter_value_does_not_leave_a_stale_tail(backlight_root: Path) -> None:
    """19200 followed by 500 must read back as 500, not 50000.

    The persistent write fd seeks to 0 rather than reopening, so without the
    truncate the previous value's tail would survive.
    """
    backlight = make_backlight(backlight_root)
    backlight.write_raw(100000)
    assert backlight.read_raw() == 100000
    backlight.write_raw(2000)
    assert backlight.read_raw() == 2000
    backlight.close()


def test_write_clamps_into_the_safe_range(backlight_root: Path) -> None:
    backlight = make_backlight(backlight_root)
    backlight.write_raw(0)
    assert backlight.read_raw() == 1920
    backlight.write_raw(10**9)
    assert backlight.read_raw() == 192000
    backlight.close()


def test_echo_detection_tolerates_quantisation(backlight_root: Path) -> None:
    """actual_brightness lands an LSB low for some values, so equality is wrong."""
    backlight = make_backlight(backlight_root)
    assert not backlight.is_own_echo(50000)  # nothing written yet
    backlight.write_raw(50000)
    assert backlight.is_own_echo(50000)
    assert backlight.is_own_echo(49999)
    assert not backlight.is_own_echo(48000)
    backlight.close()


def test_change_watch_descriptor_can_be_drained(backlight_root: Path) -> None:
    backlight = make_backlight(backlight_root)
    fd = backlight.open_change_watch()
    try:
        SysfsBacklight.drain_change_watch(fd)  # must not raise or block
    finally:
        os.close(fd)
    backlight.close()


def test_unreadable_device_raises(backlight_root: Path, tmp_path: Path) -> None:
    backlight = make_backlight(backlight_root)
    (backlight.device.path / "brightness").unlink()
    with pytest.raises(BacklightError):
        backlight.read_raw()
    backlight.close()


def test_percent_of_uses_the_configured_floor(backlight_root: Path) -> None:
    backlight = make_backlight(backlight_root)
    assert backlight.percent_of(backlight.min_raw) == pytest.approx(0.0)
    assert backlight.percent_of(backlight.max_raw) == pytest.approx(100.0)
    backlight.close()
