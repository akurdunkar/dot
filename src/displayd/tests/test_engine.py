"""Tests for the threaded engine facade."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import pytest

import displayd.applier as applier_mod
import displayd.engine as engine_mod
from displayd.backends.base import DisplayBackend
from displayd.engine import Engine
from displayd.policy import save_profile
from displayd.types import (
    ConnectedOutput,
    DisplayEvent,
    EventKind,
    MonitorIdentity,
    OutputConfig,
    Profile,
    Topology,
)

IDENTITY = MonitorIdentity("DEL", "U2720Q", "SN123")

BASE_OUTPUT = ConnectedOutput(
    connector="DP-1",
    identity=IDENTITY,
    modes=("3840x2160", "1920x1080"),
    current_mode="1920x1080",
    current_position=(0, 0),
    current_rotation="normal",
    is_primary=False,
)

BASE_TOPOLOGY = Topology(outputs=(BASE_OUTPUT,), lid_closed=False)

DESIRED = OutputConfig(
    identity=IDENTITY,
    enabled=True,
    mode="3840x2160",
    position=(0, 0),
    rotation="normal",
    primary=True,
)


class FakeBackend(DisplayBackend):
    def __init__(self, topology: Topology) -> None:
        self.topology = topology
        self.apply_calls: list[list[tuple[str, OutputConfig]]] = []
        self.apply_result = True
        self.verify_result = True

    async def get_topology(self) -> Topology:
        return self.topology

    async def apply(self, changes: list[tuple[str, OutputConfig]]) -> bool:
        self.apply_calls.append(list(changes))
        if not self.apply_result:
            return False
        outputs = []
        for o in self.topology.outputs:
            for connector, cfg in changes:
                if connector == o.connector:
                    o = ConnectedOutput(
                        connector=o.connector,
                        identity=o.identity,
                        modes=o.modes,
                        current_mode=cfg.mode if cfg.enabled else None,
                        current_position=cfg.position,
                        current_rotation=cfg.rotation,
                        is_primary=cfg.primary,
                        edid_raw=o.edid_raw,
                    )
            outputs.append(o)
        self.topology = Topology(
            outputs=tuple(outputs), lid_closed=self.topology.lid_closed
        )
        return True

    async def verify(self, changes: list[tuple[str, OutputConfig]]) -> bool:
        return self.verify_result

    def session_type(self) -> str:
        return "fake"


def wait_for(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def write_profile(profile_dir: Path, name: str, priority: int = 0) -> Profile:
    profile = Profile(
        name=name,
        topology_hash=BASE_TOPOLOGY.identity_hash,
        outputs=(DESIRED,),
        priority=priority,
    )
    save_profile(profile, profile_dir)
    return profile


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    async def no_notify(summary, body, urgency="normal"):
        return None

    monkeypatch.setattr(applier_mod, "_notify", no_notify)
    monkeypatch.setattr(engine_mod, "read_lid_state", lambda: False)
    monkeypatch.setattr(engine_mod, "RESUME_SETTLE_SECONDS", 0.05)
    monkeypatch.setattr(engine_mod, "STARTUP_SETTLE_SECONDS", 60.0)


def make_engine(profile_dir: Path, backend: FakeBackend) -> Engine:
    return Engine(
        profile_dir=profile_dir,
        cooldown=30.0,
        retries=2,
        debounce=0.05,
        settle=0.05,
        backend=backend,
        enable_watchers=False,
    )


class TestEngineLifecycle:
    def test_initial_reconcile_applies_matching_profile(self, tmp_path):
        write_profile(tmp_path, "docked")
        backend = FakeBackend(BASE_TOPOLOGY)
        engine = make_engine(tmp_path, backend)
        engine.start()
        try:
            assert wait_for(lambda: len(backend.apply_calls) >= 1)
            assert backend.apply_calls[0] == [("DP-1", DESIRED)]
            assert wait_for(lambda: engine.state.matched_profile == "docked")
            assert wait_for(lambda: engine.state.in_sync)
            assert engine.state.topology is not None
        finally:
            engine.stop()
        assert not engine._thread.is_alive()

    def test_state_listener_receives_broadcasts(self, tmp_path):
        write_profile(tmp_path, "docked")
        backend = FakeBackend(BASE_TOPOLOGY)
        engine = make_engine(tmp_path, backend)
        states: list[engine_mod.EngineState] = []
        engine.add_state_listener(states.append)
        engine.start()
        try:
            assert wait_for(lambda: len(states) >= 1)
            assert states[-1].matched_profile == "docked"
        finally:
            engine.stop()


class TestPause:
    def test_paused_engine_does_not_apply(self, tmp_path):
        write_profile(tmp_path, "docked")
        backend = FakeBackend(BASE_TOPOLOGY)
        engine = make_engine(tmp_path, backend)
        engine.start()
        try:
            assert wait_for(lambda: engine.state.in_sync)
            initial_applies = len(backend.apply_calls)

            engine.set_paused(True)
            assert engine.state.paused

            backend.topology = BASE_TOPOLOGY
            engine.inject_event(
                DisplayEvent(kind=EventKind.DRM_CHANGE, detail="test")
            )
            assert wait_for(lambda: not engine.state.in_sync)
            assert len(backend.apply_calls) == initial_applies

            engine.set_paused(False)
            engine.inject_event(
                DisplayEvent(kind=EventKind.DRM_CHANGE, detail="test")
            )
            assert wait_for(lambda: len(backend.apply_calls) > initial_applies)
        finally:
            engine.stop()


class TestCooldown:
    def test_event_does_not_revert_manual_layout(self, tmp_path):
        """A coalesced event inside the manual-change cooldown must not
        re-apply the matched profile over the user's layout."""
        write_profile(tmp_path, "docked")
        backend = FakeBackend(BASE_TOPOLOGY)
        engine = make_engine(tmp_path, backend)
        engine.start()
        try:
            assert wait_for(lambda: engine.state.in_sync)

            manual = OutputConfig(
                identity=IDENTITY,
                enabled=True,
                mode="1920x1080",
                position=(0, 0),
                rotation="normal",
                primary=False,
            )
            assert engine.apply_layout([("DP-1", manual)]).result(timeout=5)
            applies = len(backend.apply_calls)

            engine.inject_event(
                DisplayEvent(kind=EventKind.SESSION_UNLOCK, detail="test")
            )
            time.sleep(0.5)
            assert len(backend.apply_calls) == applies
            assert backend.topology.outputs[0].current_mode == "1920x1080"

            # "Sync now" is an explicit user request and must still override.
            assert engine.sync_now().result(timeout=5) is True
            assert backend.topology.outputs[0].current_mode == "3840x2160"
        finally:
            engine.stop()


class TestOperations:
    def test_apply_layout_applies_and_records_cooldown(self, tmp_path):
        backend = FakeBackend(BASE_TOPOLOGY)
        engine = make_engine(tmp_path, backend)
        engine.start()
        try:
            assert wait_for(lambda: engine.state.topology is not None)
            assert backend.apply_calls == []
            assert not engine._applier.cooldown.is_suppressed

            changes = [("DP-1", DESIRED)]
            assert engine.apply_layout(changes).result(timeout=5) is True
            assert backend.apply_calls == [changes]
            assert engine._applier.cooldown.is_suppressed
        finally:
            engine.stop()

    def test_apply_layout_records_cooldown_on_failure(self, tmp_path):
        backend = FakeBackend(BASE_TOPOLOGY)
        backend.apply_result = False
        engine = make_engine(tmp_path, backend)
        engine.start()
        try:
            assert wait_for(lambda: engine.state.topology is not None)
            changes = [("DP-1", DESIRED)]
            assert engine.apply_layout(changes).result(timeout=5) is False
            assert engine._applier.cooldown.is_suppressed
        finally:
            engine.stop()

    def test_save_layout_persists_and_reloads(self, tmp_path):
        backend = FakeBackend(BASE_TOPOLOGY)
        engine = make_engine(tmp_path, backend)
        engine.start()
        try:
            fut = engine.save_layout(
                "workbench",
                [DESIRED],
                BASE_TOPOLOGY.identity_hash,
                priority=2,
            )
            path = fut.result(timeout=5)
            assert path == tmp_path / "workbench.json"
            assert path.exists()
            assert any(p.name == "workbench" for p in engine.state.profiles)
            assert engine.state.matched_profile == "workbench"
        finally:
            engine.stop()

    def test_snapshot_and_delete_profile(self, tmp_path):
        backend = FakeBackend(BASE_TOPOLOGY)
        engine = make_engine(tmp_path, backend)
        engine.start()
        try:
            path = engine.snapshot_current("snap", priority=1).result(timeout=5)
            assert path.exists()
            assert any(p.name == "snap" for p in engine.state.profiles)

            engine.delete_profile("snap").result(timeout=5)
            assert not path.exists()
            assert all(p.name != "snap" for p in engine.state.profiles)
        finally:
            engine.stop()
