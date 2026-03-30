"""Topology snapshotting from sysfs and EDID parsing."""

from __future__ import annotations

import logging
from pathlib import Path

from .types import ConnectedOutput, MonitorIdentity, Topology, UNKNOWN_IDENTITY

log = logging.getLogger(__name__)

DRM_CLASS = Path("/sys/class/drm")

# ---------------------------------------------------------------------------
# EDID binary parsing
# ---------------------------------------------------------------------------

_EDID_HEADER = b"\x00\xff\xff\xff\xff\xff\xff\x00"


def parse_edid(raw: bytes) -> MonitorIdentity:
    """Extract manufacturer/model/serial from a raw EDID blob (>= 128 bytes)."""
    if len(raw) < 128 or raw[:8] != _EDID_HEADER:
        return UNKNOWN_IDENTITY

    # Manufacturer ID -- 2-byte big-endian compressed ASCII (A=1 .. Z=26)
    mfg_raw = (raw[8] << 8) | raw[9]
    c1 = chr(((mfg_raw >> 10) & 0x1F) + ord("A") - 1)
    c2 = chr(((mfg_raw >> 5) & 0x1F) + ord("A") - 1)
    c3 = chr((mfg_raw & 0x1F) + ord("A") - 1)
    manufacturer = f"{c1}{c2}{c3}"

    product_code = raw[10] | (raw[11] << 8)
    serial_num = raw[12] | (raw[13] << 8) | (raw[14] << 16) | (raw[15] << 24)

    model_name = ""
    serial_str = ""

    # Walk the four 18-byte descriptor blocks for human-readable strings
    for i in range(4):
        offset = 54 + i * 18
        if offset + 18 > len(raw):
            break
        desc = raw[offset : offset + 18]
        if desc[0] != 0 or desc[1] != 0:
            continue
        tag = desc[3]
        text = desc[5:18].decode("cp437", errors="replace").rstrip("\n\r \x00")
        if tag == 0xFC:
            model_name = text
        elif tag == 0xFF:
            serial_str = text

    if not model_name:
        model_name = f"{manufacturer}-{product_code:04X}"
    if not serial_str and serial_num:
        serial_str = str(serial_num)

    return MonitorIdentity(
        manufacturer=manufacturer, model=model_name, serial=serial_str
    )


# ---------------------------------------------------------------------------
# Sysfs topology reader (for the system-level daemon)
# ---------------------------------------------------------------------------


def read_sysfs_topology(*, drm_path: Path = DRM_CLASS) -> Topology:
    """Build a Topology from /sys/class/drm connector entries."""
    outputs: list[ConnectedOutput] = []

    if not drm_path.exists():
        log.warning("DRM sysfs path %s does not exist", drm_path)
        return Topology(outputs=())

    for entry in sorted(drm_path.iterdir()):
        status_file = entry / "status"
        if not status_file.exists():
            continue
        try:
            status = status_file.read_text().strip()
        except OSError:
            continue
        if status != "connected":
            continue

        connector = entry.name
        # Strip card prefix: "card0-DP-1" -> "DP-1"
        if "-" in connector:
            connector = connector.split("-", 1)[1]

        identity = UNKNOWN_IDENTITY
        edid_raw = b""
        edid_file = entry / "edid"
        if edid_file.exists():
            try:
                edid_raw = edid_file.read_bytes()
                if edid_raw:
                    identity = parse_edid(edid_raw)
            except OSError as exc:
                log.debug("Could not read EDID for %s: %s", connector, exc)

        modes: tuple[str, ...] = ()
        modes_file = entry / "modes"
        if modes_file.exists():
            try:
                modes = tuple(modes_file.read_text().strip().splitlines())
            except OSError:
                pass

        outputs.append(
            ConnectedOutput(
                connector=connector,
                identity=identity,
                modes=modes,
                edid_raw=edid_raw,
            )
        )

    return Topology(outputs=tuple(outputs))


def read_lid_state() -> bool:
    """Return True when the laptop lid is closed."""
    for candidate in (
        Path("/proc/acpi/button/lid/LID0/state"),
        Path("/proc/acpi/button/lid/LID/state"),
    ):
        if candidate.exists():
            try:
                return "closed" in candidate.read_text()
            except OSError:
                pass
    return False
