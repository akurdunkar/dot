"""Minimal EDID parsing -- just enough to label a monitor.

brightd only needs a stable identity and a human-readable name, so this parses
the header fields and the descriptor blocks and stops there.  A malformed or
truncated blob yields ``None`` rather than raising: an unlabelled slider is a
cosmetic problem, a crashed daemon is not.
"""

from __future__ import annotations

import struct

from .types import MonitorIdentity

_EDID_MIN_LENGTH = 128
_EDID_MAGIC = b"\x00\xff\xff\xff\xff\xff\xff\x00"

_DESCRIPTOR_OFFSETS = (54, 72, 90, 108)
_DESCRIPTOR_LENGTH = 18
_TAG_MONITOR_SERIAL = 0xFF
_TAG_MONITOR_NAME = 0xFC


def _decode_manufacturer(raw: int) -> str:
    """Expand the packed 3x5-bit PNP vendor code (e.g. 0x0DAF -> 'AUO')."""
    letters = [(raw >> shift) & 0x1F for shift in (10, 5, 0)]
    if any(value < 1 or value > 26 for value in letters):
        return "???"
    return "".join(chr(ord("A") + value - 1) for value in letters)


def _descriptor_text(block: bytes) -> str:
    """Decode a text descriptor payload (0x0A-terminated, space-padded)."""
    text = block[5:_DESCRIPTOR_LENGTH].split(b"\x0a")[0]
    return text.decode("ascii", errors="replace").strip()


def parse_edid(data: bytes) -> MonitorIdentity | None:
    """Parse an EDID blob into a :class:`MonitorIdentity`, or ``None``."""
    if len(data) < _EDID_MIN_LENGTH or not data.startswith(_EDID_MAGIC):
        return None

    manufacturer = _decode_manufacturer(struct.unpack(">H", data[8:10])[0])
    product: int = struct.unpack("<H", data[10:12])[0]
    serial_number: int = struct.unpack("<I", data[12:16])[0]

    name = ""
    serial_text = ""
    for offset in _DESCRIPTOR_OFFSETS:
        block = data[offset : offset + _DESCRIPTOR_LENGTH]
        if len(block) < _DESCRIPTOR_LENGTH or block[0:2] != b"\x00\x00" or block[2] != 0:
            continue  # a pixel-clock timing descriptor, not a text one
        if block[3] == _TAG_MONITOR_NAME:
            name = _descriptor_text(block)
        elif block[3] == _TAG_MONITOR_SERIAL:
            serial_text = _descriptor_text(block)

    # Prefer the printable serial descriptor; fall back to the numeric field.
    # Some panels (including this laptop's AUO) supply neither.
    serial = serial_text or (f"{serial_number:08X}" if serial_number else "")
    model = name or f"{product:04X}"
    return MonitorIdentity(
        manufacturer=manufacturer,
        model=model,
        serial=serial,
        name=name,
    )
