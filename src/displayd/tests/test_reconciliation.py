"""Tests for reconciliation planning -- edge cases and connector resolution."""

from __future__ import annotations

import pytest

from displayd.policy import plan_reconciliation
from displayd.types import (
    ConnectedOutput,
    MonitorIdentity,
    OutputConfig,
    Profile,
    Topology,
)


def _topo(
    *specs: tuple[str, str, str, str, str, tuple[int, int], str, bool],
) -> Topology:
    return Topology(
        outputs=tuple(
            ConnectedOutput(
                connector=c,
                identity=MonitorIdentity(m, mod, s),
                current_mode=mode,
                current_position=pos,
                current_rotation=rot,
                is_primary=pri,
            )
            for c, m, mod, s, mode, pos, rot, pri in specs
        )
    )


def _prof(
    topo: Topology,
    configs: list[tuple[str, str, str, str, tuple[int, int], str, bool]],
) -> Profile:
    return Profile(
        name="test",
        topology_hash=topo.identity_hash,
        outputs=tuple(
            OutputConfig(
                identity=MonitorIdentity(m, mod, s),
                enabled=True,
                mode=mode,
                position=pos,
                rotation=rot,
                primary=pri,
            )
            for m, mod, s, mode, pos, rot, pri in configs
        ),
    )


class TestReconciliationEdgeCases:
    def test_noop_when_state_matches(self):
        topo = _topo(("DP-1", "DEL", "M", "S", "3440x1440", (0, 0), "normal", True))
        prof = _prof(topo, [("DEL", "M", "S", "3440x1440", (0, 0), "normal", True)])
        assert plan_reconciliation(topo, prof).is_noop

    def test_mode_change(self):
        topo = _topo(("DP-1", "DEL", "M", "S", "1920x1080", (0, 0), "normal", False))
        prof = _prof(topo, [("DEL", "M", "S", "3440x1440", (0, 0), "normal", False)])
        plan = plan_reconciliation(topo, prof)
        assert not plan.is_noop
        assert len(plan.changes) == 1
        assert plan.changes[0][0] == "DP-1"

    def test_rotation_change(self):
        topo = _topo(("DP-1", "DEL", "M", "S", "1920x1200", (0, 0), "normal", False))
        prof = _prof(topo, [("DEL", "M", "S", "1920x1200", (0, 0), "left", False)])
        plan = plan_reconciliation(topo, prof)
        assert not plan.is_noop
        assert plan.changes[0][1].rotation == "left"

    def test_position_change(self):
        topo = _topo(
            ("DP-1", "DEL", "M1", "S1", "3440x1440", (0, 0), "normal", True),
            ("DP-2", "SAM", "M2", "S2", "1920x1200", (3440, 0), "normal", False),
        )
        prof = _prof(topo, [
            ("DEL", "M1", "S1", "3440x1440", (0, 0), "normal", True),
            ("SAM", "M2", "S2", "1920x1200", (3440, 100), "normal", False),
        ])
        plan = plan_reconciliation(topo, prof)
        assert not plan.is_noop
        assert len(plan.changes) == 1

    def test_primary_flag_swap(self):
        topo = _topo(
            ("DP-1", "DEL", "M1", "S1", "3440x1440", (0, 0), "normal", False),
            ("DP-2", "SAM", "M2", "S2", "1920x1080", (3440, 0), "normal", True),
        )
        prof = _prof(topo, [
            ("DEL", "M1", "S1", "3440x1440", (0, 0), "normal", True),
            ("SAM", "M2", "S2", "1920x1080", (3440, 0), "normal", False),
        ])
        plan = plan_reconciliation(topo, prof)
        assert not plan.is_noop
        assert len(plan.changes) == 2

    def test_missing_monitor_gracefully_skipped(self):
        topo = _topo(("DP-1", "DEL", "M1", "S1", "3440x1440", (0, 0), "normal", False))
        prof = Profile(
            name="two-mon",
            topology_hash=topo.identity_hash,
            outputs=(
                OutputConfig(
                    identity=MonitorIdentity("DEL", "M1", "S1"),
                    mode="3440x1440",
                    position=(0, 0),
                ),
                OutputConfig(
                    identity=MonitorIdentity("LEN", "Gone", "Z"),
                    mode="1920x1080",
                    position=(3440, 0),
                ),
            ),
        )
        plan = plan_reconciliation(topo, prof)
        connectors = [c for c, _ in plan.changes]
        assert "Gone" not in connectors

    def test_connector_resolved_by_identity_not_name(self):
        """If a monitor moves from DP-1 to DP-3, identity resolves it."""
        topo = _topo(("DP-3", "DEL", "UW", "S1", "3440x1440", (0, 0), "normal", False))
        prof = _prof(topo, [("DEL", "UW", "S1", "2560x1440", (0, 0), "normal", False)])
        plan = plan_reconciliation(topo, prof)
        assert not plan.is_noop
        assert plan.changes[0][0] == "DP-3"

    def test_disabled_output_that_is_active_needs_change(self):
        topo = _topo(
            ("DP-1", "DEL", "UW", "S1", "3440x1440", (0, 0), "normal", True),
            ("eDP-1", "AUO", "Panel", "L", "1920x1200", (0, 0), "normal", False),
        )
        prof = Profile(
            name="docked",
            topology_hash=topo.identity_hash,
            outputs=(
                OutputConfig(
                    identity=MonitorIdentity("DEL", "UW", "S1"),
                    enabled=True, mode="3440x1440", position=(0, 0), primary=True,
                ),
                OutputConfig(
                    identity=MonitorIdentity("AUO", "Panel", "L"),
                    enabled=False,
                ),
            ),
        )
        plan = plan_reconciliation(topo, prof)
        assert not plan.is_noop
        off_changes = [(c, cfg) for c, cfg in plan.changes if not cfg.enabled]
        assert len(off_changes) == 1
        assert off_changes[0][0] == "eDP-1"

    def test_disabled_output_already_off_is_noop(self):
        topo = _topo(
            ("DP-1", "DEL", "UW", "S1", "3440x1440", (0, 0), "normal", True),
            ("eDP-1", "AUO", "Panel", "L", None, (0, 0), "normal", False),
        )
        prof = Profile(
            name="docked",
            topology_hash=topo.identity_hash,
            outputs=(
                OutputConfig(
                    identity=MonitorIdentity("DEL", "UW", "S1"),
                    enabled=True, mode="3440x1440", position=(0, 0), primary=True,
                ),
                OutputConfig(
                    identity=MonitorIdentity("AUO", "Panel", "L"),
                    enabled=False,
                ),
            ),
        )
        assert plan_reconciliation(topo, prof).is_noop

    def test_empty_profile_is_noop(self):
        topo = _topo(("DP-1", "DEL", "M", "S", "3440x1440", (0, 0), "normal", False))
        prof = Profile(name="empty", topology_hash=topo.identity_hash, outputs=())
        assert plan_reconciliation(topo, prof).is_noop


class TestTwinMonitors:
    """Identical monitors (same manufacturer/model, missing serials) fuzzy-
    match each other; each must still resolve to its own connector."""

    def test_twin_serialless_monitors_each_get_their_own_connector(self):
        topo = _topo(
            ("DP-1", "ACR", "K242HL", "", "1920x1080", (0, 0), "normal", True),
            ("DP-2", "ACR", "K242HL", "", "1920x1080", (0, 0), "normal", False),
        )
        prof = _prof(topo, [
            ("ACR", "K242HL", "", "1920x1080", (0, 0), "normal", True),
            ("ACR", "K242HL", "", "1920x1080", (1920, 0), "normal", False),
        ])
        plan = plan_reconciliation(topo, prof)
        assert [c for c, _ in plan.changes] == ["DP-2"]
        assert plan.changes[0][1].position == (1920, 0)

    def test_twin_monitors_never_duplicate_a_connector(self):
        topo = _topo(
            ("DP-1", "ACR", "K242HL", "", "1920x1080", (5, 5), "normal", False),
            ("DP-2", "ACR", "K242HL", "", "1920x1080", (7, 7), "normal", False),
        )
        prof = _prof(topo, [
            ("ACR", "K242HL", "", "1920x1080", (0, 0), "normal", True),
            ("ACR", "K242HL", "", "1920x1080", (1920, 0), "normal", False),
        ])
        plan = plan_reconciliation(topo, prof)
        connectors = [c for c, _ in plan.changes]
        assert sorted(connectors) == ["DP-1", "DP-2"]


class TestScale:
    def test_scale_only_difference_needs_change(self):
        topo = _topo(("DP-1", "DEL", "M", "S", "3440x1440", (0, 0), "normal", False))
        prof = Profile(
            name="scaled",
            topology_hash=topo.identity_hash,
            outputs=(
                OutputConfig(
                    identity=MonitorIdentity("DEL", "M", "S"),
                    mode="3440x1440",
                    position=(0, 0),
                    scale=1.5,
                ),
            ),
        )
        plan = plan_reconciliation(topo, prof)
        assert not plan.is_noop
        assert plan.changes[0][1].scale == 1.5

    def test_matching_scale_is_noop(self):
        topo = Topology(
            outputs=(
                ConnectedOutput(
                    connector="DP-1",
                    identity=MonitorIdentity("DEL", "M", "S"),
                    current_mode="3440x1440",
                    current_position=(0, 0),
                    current_scale=1.5,
                ),
            )
        )
        prof = Profile(
            name="scaled",
            topology_hash=topo.identity_hash,
            outputs=(
                OutputConfig(
                    identity=MonitorIdentity("DEL", "M", "S"),
                    mode="3440x1440",
                    position=(0, 0),
                    scale=1.5,
                ),
            ),
        )
        assert plan_reconciliation(topo, prof).is_noop
