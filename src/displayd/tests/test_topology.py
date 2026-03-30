"""Tests for EDID parsing and topology hashing."""

from __future__ import annotations

import pytest

from displayd.topology import parse_edid
from displayd.types import ConnectedOutput, MonitorIdentity, Topology, UNKNOWN_IDENTITY


# ---------------------------------------------------------------------------
# EDID test helpers
# ---------------------------------------------------------------------------


def _encode_manufacturer(chars: str) -> tuple[int, int]:
    c1 = ord(chars[0]) - ord("A") + 1
    c2 = ord(chars[1]) - ord("A") + 1
    c3 = ord(chars[2]) - ord("A") + 1
    val = (c1 << 10) | (c2 << 5) | c3
    return (val >> 8) & 0xFF, val & 0xFF


def _write_descriptor(
    edid: bytearray, offset: int, tag: int, text: str
) -> None:
    edid[offset] = 0
    edid[offset + 1] = 0
    edid[offset + 2] = 0
    edid[offset + 3] = tag
    edid[offset + 4] = 0
    raw = text.encode("ascii")[:13].ljust(13, b"\n")
    edid[offset + 5 : offset + 18] = raw


def _make_edid(
    mfg: str,
    product: int = 0,
    serial: int = 0,
    model_name: str = "",
    serial_str: str = "",
) -> bytes:
    edid = bytearray(128)
    edid[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    hi, lo = _encode_manufacturer(mfg)
    edid[8] = hi
    edid[9] = lo
    edid[10] = product & 0xFF
    edid[11] = (product >> 8) & 0xFF
    edid[12] = serial & 0xFF
    edid[13] = (serial >> 8) & 0xFF
    edid[14] = (serial >> 16) & 0xFF
    edid[15] = (serial >> 24) & 0xFF
    if model_name:
        _write_descriptor(edid, 54, 0xFC, model_name)
    if serial_str:
        _write_descriptor(edid, 72, 0xFF, serial_str)
    return bytes(edid)


# ---------------------------------------------------------------------------
# EDID parsing
# ---------------------------------------------------------------------------


class TestEdidParsing:
    def test_valid_edid_with_descriptors(self):
        raw = _make_edid("DEL", 0x1234, 99999, "U3423WE", "SN12345")
        ident = parse_edid(raw)
        assert ident.manufacturer == "DEL"
        assert ident.model == "U3423WE"
        assert ident.serial == "SN12345"

    def test_edid_without_descriptors_falls_back(self):
        raw = _make_edid("SAM", 0xABCD, 42)
        ident = parse_edid(raw)
        assert ident.manufacturer == "SAM"
        assert "ABCD" in ident.model
        assert ident.serial == "42"

    def test_empty_edid(self):
        assert parse_edid(b"") is UNKNOWN_IDENTITY

    def test_short_edid(self):
        assert parse_edid(b"\x00" * 50) is UNKNOWN_IDENTITY

    def test_bad_header(self):
        assert parse_edid(b"\x01" * 128) is UNKNOWN_IDENTITY

    def test_manufacturer_round_trip(self):
        for code in ("DEL", "SAM", "BOE", "AUO", "LGD"):
            raw = _make_edid(code, model_name="Test")
            assert parse_edid(raw).manufacturer == code


# ---------------------------------------------------------------------------
# Topology hashing
# ---------------------------------------------------------------------------


def _topo(*monitors: tuple[str, str, str, str]) -> Topology:
    return Topology(
        outputs=tuple(
            ConnectedOutput(connector=c, identity=MonitorIdentity(m, mod, s))
            for c, m, mod, s in monitors
        )
    )


class TestTopologyHashing:
    def test_identity_hash_stable_across_connector_rename(self):
        t1 = _topo(("DP-1", "DEL", "U3423WE", "A"))
        t2 = _topo(("DP-3", "DEL", "U3423WE", "A"))
        assert t1.identity_hash == t2.identity_hash

    def test_different_monitors_different_hash(self):
        t1 = _topo(("DP-1", "DEL", "U3423WE", "A"))
        t2 = _topo(("DP-1", "SAM", "LC49G95T", "B"))
        assert t1.identity_hash != t2.identity_hash

    def test_order_independent(self):
        t1 = _topo(("DP-1", "DEL", "UW", "A"), ("HDMI-1", "SAM", "M", "B"))
        t2 = _topo(("HDMI-1", "SAM", "M", "B"), ("DP-1", "DEL", "UW", "A"))
        assert t1.identity_hash == t2.identity_hash

    def test_lid_state_affects_identity_hash(self):
        base = (ConnectedOutput(
            connector="eDP-1", identity=MonitorIdentity("BOE", "NV156", "X")
        ),)
        t_open = Topology(outputs=base, lid_closed=False)
        t_closed = Topology(outputs=base, lid_closed=True)
        assert t_open.identity_hash != t_closed.identity_hash

    def test_full_state_hash_includes_mode(self):
        t1 = Topology(outputs=(ConnectedOutput(
            connector="DP-1",
            identity=MonitorIdentity("DEL", "M", "S"),
            current_mode="3440x1440",
        ),))
        t2 = Topology(outputs=(ConnectedOutput(
            connector="DP-1",
            identity=MonitorIdentity("DEL", "M", "S"),
            current_mode="1920x1080",
        ),))
        assert t1.full_state_hash != t2.full_state_hash

    def test_empty_topology(self):
        t = Topology(outputs=())
        assert isinstance(t.identity_hash, str)
        assert t.monitor_count == 0


# ---------------------------------------------------------------------------
# MonitorIdentity matching
# ---------------------------------------------------------------------------


class TestMonitorIdentity:
    def test_exact_match(self):
        a = MonitorIdentity("DEL", "U3423WE", "ABC")
        b = MonitorIdentity("DEL", "U3423WE", "ABC")
        assert a.matches(b)

    def test_serial_mismatch(self):
        a = MonitorIdentity("DEL", "U3423WE", "ABC")
        b = MonitorIdentity("DEL", "U3423WE", "XYZ")
        assert not a.matches(b)

    def test_empty_serial_matches(self):
        a = MonitorIdentity("DEL", "U3423WE", "")
        b = MonitorIdentity("DEL", "U3423WE", "ABC")
        assert a.matches(b)

    def test_both_empty_serial(self):
        a = MonitorIdentity("DEL", "U3423WE", "")
        b = MonitorIdentity("DEL", "U3423WE", "")
        assert a.matches(b)

    def test_manufacturer_mismatch(self):
        a = MonitorIdentity("DEL", "U3423WE", "ABC")
        b = MonitorIdentity("SAM", "U3423WE", "ABC")
        assert not a.matches(b)

    def test_model_mismatch(self):
        a = MonitorIdentity("DEL", "U3423WE", "ABC")
        b = MonitorIdentity("DEL", "P2720D", "ABC")
        assert not a.matches(b)

    def test_stable_id_format(self):
        m = MonitorIdentity("DEL", "U3423WE", "SN1")
        assert m.stable_id == "DEL/U3423WE/SN1"
