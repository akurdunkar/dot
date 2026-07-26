"""Tests for the applier's post-apply state recording."""

from __future__ import annotations

import asyncio

import pytest

import displayd.applier as applier_mod
from displayd.applier import DisplayApplier
from displayd.backends.base import DisplayBackend
from displayd.types import (
    ConnectedOutput,
    MonitorIdentity,
    OutputConfig,
    Profile,
    Topology,
)

IDENTITY = MonitorIdentity("DEL", "U2720Q", "SN123")
NEW_IDENTITY = MonitorIdentity("SAM", "S27", "SN999")


def _output(identity, connector, mode):
    return ConnectedOutput(
        connector=connector,
        identity=identity,
        modes=("3840x2160", "1920x1080"),
        current_mode=mode,
    )


BASE = Topology(outputs=(_output(IDENTITY, "DP-1", "1920x1080"),))


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    async def no_notify(summary, body, urgency="normal"):
        return None

    monkeypatch.setattr(applier_mod, "_notify", no_notify)


class HotplugDuringApplyBackend(DisplayBackend):
    """A second monitor appears while the apply/verify window is open."""

    def __init__(self) -> None:
        self.applied = False

    async def get_topology(self) -> Topology:
        if self.applied:
            return Topology(
                outputs=(
                    _output(IDENTITY, "DP-1", "3840x2160"),
                    _output(NEW_IDENTITY, "DP-2", None),
                )
            )
        return BASE

    async def apply(self, changes) -> bool:
        self.applied = True
        return True

    async def verify(self, changes) -> bool:
        return True

    def session_type(self) -> str:
        return "fake"


def test_hotplug_during_apply_does_not_poison_unchanged_hash():
    """A monitor plugged during the apply window must not have its
    unconfigured state recorded as 'applied': the pending hotplug event's
    reconcile would then short-circuit and leave it black."""
    profile = Profile(
        name="docked",
        topology_hash=BASE.identity_hash,
        outputs=(OutputConfig(identity=IDENTITY, mode="3840x2160"),),
    )
    backend = HotplugDuringApplyBackend()
    applier = DisplayApplier(
        backend=backend,
        profiles=[profile],
        verify_delay=0.01,
        retry_delay=0.01,
    )
    assert asyncio.run(applier.reconcile(force=True)) is True
    assert applier._last_applied_hash == ""


def test_manual_apply_with_failed_baseline_clears_hash():
    """If the pre-apply topology read failed, the race cannot be ruled out;
    the hash must be cleared, not recorded from the post-apply read."""

    class FlakyBaselineBackend(DisplayBackend):
        def __init__(self) -> None:
            self.calls = 0

        async def get_topology(self) -> Topology:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("X briefly unreachable")
            return BASE

        async def apply(self, changes) -> bool:
            return True

        async def verify(self, changes) -> bool:
            return True

        def session_type(self) -> str:
            return "fake"

    applier = DisplayApplier(
        backend=FlakyBaselineBackend(), profiles=[], verify_delay=0.01
    )
    applier._last_applied_hash = "poisoned"
    ok = asyncio.run(
        applier.apply_manual(
            [("DP-1", OutputConfig(identity=IDENTITY, mode="3840x2160"))]
        )
    )
    assert ok is True
    assert applier._last_applied_hash == ""


def test_stable_monitor_set_records_applied_hash():
    """The guard must not fire when the monitor set is unchanged."""

    class StableBackend(HotplugDuringApplyBackend):
        async def get_topology(self) -> Topology:
            if self.applied:
                return Topology(outputs=(_output(IDENTITY, "DP-1", "3840x2160"),))
            return BASE

    profile = Profile(
        name="docked",
        topology_hash=BASE.identity_hash,
        outputs=(OutputConfig(identity=IDENTITY, mode="3840x2160"),),
    )
    backend = StableBackend()
    applier = DisplayApplier(
        backend=backend,
        profiles=[profile],
        verify_delay=0.01,
        retry_delay=0.01,
    )
    assert asyncio.run(applier.reconcile(force=True)) is True
    assert applier._last_applied_hash != ""
