"""Tests for profile matching and snapshot helpers."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from displayd.policy import (
    load_profiles,
    match_profile,
    save_profile,
    snapshot_to_profile,
)
from displayd.types import (
    ConnectedOutput,
    MonitorIdentity,
    OutputConfig,
    Profile,
    Topology,
)


def _topo(*specs: tuple[str, str, str, str, str, tuple[int, int]]) -> Topology:
    return Topology(
        outputs=tuple(
            ConnectedOutput(
                connector=c,
                identity=MonitorIdentity(m, mod, s),
                current_mode=mode,
                current_position=pos,
            )
            for c, m, mod, s, mode, pos in specs
        )
    )


def _profile(
    name: str,
    topo: Topology,
    configs: list[tuple[MonitorIdentity, str, tuple[int, int], bool]],
    priority: int = 0,
) -> Profile:
    return Profile(
        name=name,
        topology_hash=topo.identity_hash,
        outputs=tuple(
            OutputConfig(identity=ident, enabled=True, mode=mode, position=pos, primary=pri)
            for ident, mode, pos, pri in configs
        ),
        priority=priority,
    )


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


class TestMatchProfile:
    def test_exact_match(self):
        topo = _topo(("DP-1", "DEL", "UW", "A", "3440x1440", (0, 0)))
        prof = _profile(
            "docked",
            topo,
            [(MonitorIdentity("DEL", "UW", "A"), "3440x1440", (0, 0), True)],
        )
        assert match_profile(topo, [prof]) is prof

    def test_no_match_returns_none(self):
        topo = _topo(("DP-1", "DEL", "UW", "A", "3440x1440", (0, 0)))
        other = _topo(("DP-1", "SAM", "X", "B", "1080p", (0, 0)))
        prof = _profile(
            "other",
            other,
            [(MonitorIdentity("SAM", "X", "B"), "1080p", (0, 0), False)],
        )
        assert match_profile(topo, [prof]) is None

    def test_highest_priority_wins(self):
        topo = _topo(("DP-1", "DEL", "UW", "A", "3440x1440", (0, 0)))
        lo = _profile(
            "low", topo,
            [(MonitorIdentity("DEL", "UW", "A"), "1080p", (0, 0), False)],
            priority=1,
        )
        hi = _profile(
            "high", topo,
            [(MonitorIdentity("DEL", "UW", "A"), "3440x1440", (0, 0), True)],
            priority=10,
        )
        assert match_profile(topo, [lo, hi]) is hi

    def test_empty_profile_list(self):
        topo = _topo(("DP-1", "DEL", "UW", "A", "3440x1440", (0, 0)))
        assert match_profile(topo, []) is None


# ---------------------------------------------------------------------------
# Snapshot / round-trip
# ---------------------------------------------------------------------------


class TestSnapshotToProfile:
    def test_captures_state(self):
        topo = _topo(
            ("DP-1", "DEL", "UW", "A", "3440x1440", (0, 0)),
            ("eDP-1", "BOE", "Laptop", "L", "1920x1080", (3440, 0)),
        )
        prof = snapshot_to_profile("my-setup", topo)
        assert prof.name == "my-setup"
        assert prof.topology_hash == topo.identity_hash
        assert len(prof.outputs) == 2

    def test_json_round_trip(self):
        topo = _topo(("DP-1", "DEL", "UW", "A", "3440x1440", (0, 0)))
        prof = snapshot_to_profile("rt", topo, priority=5)
        data = json.loads(json.dumps(prof.to_dict()))
        restored = Profile.from_dict(data)
        assert restored.name == "rt"
        assert restored.topology_hash == prof.topology_hash
        assert restored.priority == 5
        assert len(restored.outputs) == 1


# ---------------------------------------------------------------------------
# Profile persistence
# ---------------------------------------------------------------------------


class TestProfilePersistence:
    def test_save_and_load(self, tmp_path: Path):
        prof = Profile(
            name="test-profile",
            topology_hash="abc123",
            priority=7,
            outputs=(
                OutputConfig(
                    identity=MonitorIdentity("DEL", "UW", "SN1"),
                    enabled=True,
                    mode="3440x1440",
                    position=(0, 0),
                    primary=True,
                ),
            ),
        )
        save_profile(prof, tmp_path)
        loaded = load_profiles(tmp_path)
        assert len(loaded) == 1
        assert loaded[0].name == "test-profile"
        assert loaded[0].priority == 7
        assert loaded[0].outputs[0].identity.stable_id == "DEL/UW/SN1"

    def test_load_skips_invalid_json(self, tmp_path: Path):
        (tmp_path / "bad.json").write_text("NOT JSON")
        loaded = load_profiles(tmp_path)
        assert loaded == []

    def test_load_empty_dir(self, tmp_path: Path):
        assert load_profiles(tmp_path) == []

    def test_load_nonexistent_dir(self):
        assert load_profiles(Path("/nonexistent/path")) == []
