"""EDID parsing. Malformed blobs must degrade, never raise."""

from __future__ import annotations

from brightd.edid import parse_edid

from .conftest import make_edid


def test_parses_manufacturer_name_and_serial() -> None:
    identity = parse_edid(make_edid())
    assert identity is not None
    assert identity.manufacturer == "DEL"
    assert identity.name == "U2720Q"
    assert identity.serial == "ABC123"
    assert identity.label == "U2720Q"


def test_falls_back_to_the_numeric_serial() -> None:
    identity = parse_edid(make_edid(serial_text=""))
    assert identity is not None
    assert identity.serial == "DEADBEEF"


def test_panel_with_no_serial_at_all() -> None:
    """Exactly the case of this laptop's AUO panel."""
    identity = parse_edid(make_edid(serial_text="", serial_number=0))
    assert identity is not None
    assert identity.serial == ""
    assert identity.stable_id.endswith("/")


def test_label_falls_back_to_manufacturer_and_model() -> None:
    identity = parse_edid(make_edid(name=""))
    assert identity is not None
    assert identity.name == ""
    assert identity.label.startswith("DEL ")


def test_rejects_a_bad_header() -> None:
    assert parse_edid(b"\x00" * 128) is None


def test_rejects_a_truncated_blob() -> None:
    assert parse_edid(make_edid()[:64]) is None


def test_rejects_an_empty_blob() -> None:
    assert parse_edid(b"") is None


def test_unprintable_manufacturer_does_not_raise() -> None:
    identity = parse_edid(make_edid(manufacturer=0x0000))
    assert identity is not None
    assert identity.manufacturer == "???"
