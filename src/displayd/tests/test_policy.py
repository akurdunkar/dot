"""Tests for profile matching and snapshot helpers."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from dataclasses import replace

from displayd.policy import (
    load_profiles,
    match_profile,
    profile_matches_monitor_set,
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

    def test_lid_state_distinguishes_topologies_for_auto_match(self):
        open_topo = _topo(("DP-1", "DEL", "UW", "A", "3440x1440", (0, 0)))
        closed_topo = replace(open_topo, lid_closed=True)
        prof = _profile(
            "open-lid",
            open_topo,
            [(MonitorIdentity("DEL", "UW", "A"), "3440x1440", (0, 0), True)],
        )
        assert match_profile(open_topo, [prof]) is prof
        assert match_profile(closed_topo, [prof]) is None

    def test_manual_match_ignores_lid_state(self):
        """Explicitly switching to a same-monitor profile saved with the lid
        in the other position must be allowed (clamshell users)."""
        open_topo = _topo(("DP-1", "DEL", "UW", "A", "3440x1440", (0, 0)))
        closed_topo = replace(open_topo, lid_closed=True)
        prof = _profile(
            "open-lid",
            open_topo,
            [(MonitorIdentity("DEL", "UW", "A"), "3440x1440", (0, 0), True)],
        )
        assert profile_matches_monitor_set(prof, open_topo)
        assert profile_matches_monitor_set(prof, closed_topo)
        other = _topo(("DP-1", "SAM", "X", "B", "1080p", (0, 0)))
        assert not profile_matches_monitor_set(prof, other)


class TestFullStateHash:
    def test_tracks_primary_and_scale_drift(self):
        """primary/scale drift must change the hash or the applier's
        unchanged-state short-circuit hides it from reconciliation."""
        base = ConnectedOutput(
            connector="DP-1",
            identity=MonitorIdentity("DEL", "M", "S"),
            current_mode="1920x1080",
        )
        t0 = Topology(outputs=(base,))
        t_primary = Topology(outputs=(replace(base, is_primary=True),))
        t_scale = Topology(outputs=(replace(base, current_scale=1.5),))
        assert t0.full_state_hash != t_primary.full_state_hash
        assert t0.full_state_hash != t_scale.full_state_hash
        assert t0.identity_hash == t_primary.identity_hash


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

    def test_round_trip_preserves_slash_in_model(self):
        """EDID model strings can contain '/' (e.g. AOC 'Q27G2S/EU'); the
        identity must survive save/load field-for-field."""
        prof = Profile(
            name="slash",
            topology_hash="abc",
            outputs=(
                OutputConfig(
                    identity=MonitorIdentity("AOC", "Q27G2S/EU", "123"),
                    mode="2560x1440",
                ),
            ),
        )
        restored = Profile.from_dict(json.loads(json.dumps(prof.to_dict())))
        ident = restored.outputs[0].identity
        assert ident.manufacturer == "AOC"
        assert ident.model == "Q27G2S/EU"
        assert ident.serial == "123"

    def test_legacy_identity_string_still_loads(self):
        data = {
            "name": "legacy",
            "topology_hash": "abc",
            "outputs": [{"identity": "DEL/U2720Q/SN1", "mode": "3840x2160"}],
        }
        prof = Profile.from_dict(data)
        ident = prof.outputs[0].identity
        assert (ident.manufacturer, ident.model, ident.serial) == (
            "DEL",
            "U2720Q",
            "SN1",
        )

    def test_round_trip_preserves_scale(self):
        prof = Profile(
            name="scaled",
            topology_hash="abc",
            outputs=(
                OutputConfig(
                    identity=MonitorIdentity("DEL", "UW", "1"),
                    mode="3440x1440",
                    scale=1.25,
                ),
            ),
        )
        restored = Profile.from_dict(json.loads(json.dumps(prof.to_dict())))
        assert restored.outputs[0].scale == 1.25


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
