"""Connector discovery from a fake /sys/class/drm tree."""

from __future__ import annotations

from pathlib import Path

from brightd.backends.discovery import external_connectors, scan_connectors


def test_scans_every_connector(drm_root: Path) -> None:
    names = {connector.name for connector in scan_connectors(drm_root)}
    assert names == {"eDP-1", "DP-1", "DP-2"}


def test_reads_status_bus_and_identity(drm_root: Path) -> None:
    by_name = {connector.name: connector for connector in scan_connectors(drm_root)}

    external = by_name["DP-1"]
    assert external.connected
    assert external.bus == 16
    assert external.identity is not None
    assert external.identity.manufacturer == "DEL"
    assert external.identity.name == "U2720Q"
    assert not external.is_internal

    disconnected = by_name["DP-2"]
    assert not disconnected.connected
    assert disconnected.identity is None  # zero-length edid


def test_backlight_subdirectory_marks_a_panel_internal(drm_root: Path) -> None:
    """The internal panel has a working I2C bus and a valid EDID.

    So it would be scanned as a DDC candidate on those signals alone -- the
    backlight subdirectory is what keeps brightd from fighting the kernel for
    control of the same panel.
    """
    internal = next(c for c in scan_connectors(drm_root) if c.name == "eDP-1")
    assert internal.bus == 15
    assert internal.has_backlight
    assert internal.is_internal


def test_external_connectors_excludes_internal_and_disconnected(drm_root: Path) -> None:
    external = external_connectors(drm_root)
    assert [connector.name for connector in external] == ["DP-1"]


def test_connector_without_ddc_link_is_not_external(drm_root: Path) -> None:
    (drm_root / "card2-DP-1" / "ddc").unlink()
    assert external_connectors(drm_root) == []


def test_missing_root_is_not_an_error(tmp_path: Path) -> None:
    assert scan_connectors(tmp_path / "absent") == []


def test_label_falls_back_to_the_connector_name(drm_root: Path) -> None:
    internal = next(c for c in scan_connectors(drm_root) if c.name == "eDP-1")
    # The fixture's internal panel has no name or serial descriptor, exactly
    # like the real AUO panel on this laptop.
    assert internal.label
