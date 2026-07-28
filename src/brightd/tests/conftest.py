"""Fake sysfs trees, so every test runs with no hardware attached."""

from __future__ import annotations

from pathlib import Path

import pytest


def make_edid(
    *,
    manufacturer: int = 0x10AC,  # "DEL"
    product: int = 0x1234,
    serial_number: int = 0xDEADBEEF,
    name: str = "U2720Q",
    serial_text: str = "ABC123",
) -> bytes:
    """Build a minimal but structurally valid 128-byte EDID block."""
    data = bytearray(128)
    data[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    data[8:10] = manufacturer.to_bytes(2, "big")
    data[10:12] = product.to_bytes(2, "little")
    data[12:16] = serial_number.to_bytes(4, "little")

    def descriptor(offset: int, tag: int, text: str) -> None:
        data[offset : offset + 3] = b"\x00\x00\x00"
        data[offset + 3] = tag
        data[offset + 4] = 0
        payload = (text.encode("ascii") + b"\x0a").ljust(13, b" ")[:13]
        data[offset + 5 : offset + 18] = payload

    if name:
        descriptor(54, 0xFC, name)
    if serial_text:
        descriptor(72, 0xFF, serial_text)
    return bytes(data)


@pytest.fixture
def backlight_root(tmp_path: Path) -> Path:
    """A fake /sys/class/backlight with one intel_backlight on eDP-1.

    Built as a symlink into a connector directory so the connector-name
    resolution -- which reads the ``device`` link's parent -- is exercised for
    real rather than stubbed.
    """
    connector = tmp_path / "devices" / "card2-eDP-1"
    device = connector / "intel_backlight"
    device.mkdir(parents=True)
    (device / "brightness").write_text("19200\n")
    (device / "actual_brightness").write_text("19200\n")
    (device / "max_brightness").write_text("192000\n")
    (device / "type").write_text("raw\n")

    root = tmp_path / "class" / "backlight"
    root.mkdir(parents=True)
    (root / "intel_backlight").symlink_to(device)
    return root


@pytest.fixture
def drm_root(tmp_path: Path) -> Path:
    """A fake /sys/class/drm: internal eDP-1 plus one connected external DP-1."""
    root = tmp_path / "drm"
    root.mkdir()
    (root / "i2c-15").mkdir()
    (root / "i2c-16").mkdir()

    internal = root / "card2-eDP-1"
    (internal / "intel_backlight").mkdir(parents=True)
    (internal / "status").write_text("connected\n")
    (internal / "edid").write_bytes(make_edid(name="", serial_text=""))
    (internal / "ddc").symlink_to(root / "i2c-15")

    external = root / "card2-DP-1"
    external.mkdir()
    (external / "status").write_text("connected\n")
    (external / "edid").write_bytes(make_edid())
    (external / "ddc").symlink_to(root / "i2c-16")

    absent = root / "card2-DP-2"
    absent.mkdir()
    (absent / "status").write_text("disconnected\n")
    (absent / "edid").write_bytes(b"")
    return root
