"""Tests for ghost-output cleanup (disconnected outputs still holding a CRTC).

A ghost CRTC keeps the Type-C PHY occupied, which blocks the PD firmware
from renegotiating DisplayPort alt mode on replug -- the monitor then never
reappears.  Cleanup must therefore run on every reconcile cycle, not just
when a profile apply happens.
"""

from __future__ import annotations

import asyncio

import displayd.backends.xrandr as xrandr_mod
from displayd.applier import DisplayApplier
from displayd.backends.base import DisplayBackend
from displayd.backends.xrandr import XrandrBackend, _parse_xrandr_verbose
from displayd.types import ConnectedOutput, MonitorIdentity, OutputConfig, Topology

GHOST_XRANDR = """\
Screen 0: minimum 320 x 200, current 1920 x 1200, maximum 16384 x 16384
eDP-1 connected primary 1920x1200+0+0 (0x123) normal (normal left inverted right x axis y axis) 301mm x 188mm
  1920x1200 (0x124) 193.250MHz +HSync -VSync *current +preferred
DP-1 disconnected 3440x1440+0+0 (0x125) normal (normal left inverted right x axis y axis) 0mm x 0mm
DP-2 disconnected (normal left inverted right x axis y axis)
"""


TWO_GHOST_XRANDR = """\
Screen 0: minimum 320 x 200, current 1920 x 1200, maximum 16384 x 16384
eDP-1 connected primary 1920x1200+0+0 (0x123) normal (normal left inverted right x axis y axis) 301mm x 188mm
  1920x1200 (0x124) 193.250MHz +HSync -VSync *current +preferred
DP-1 disconnected 3440x1440+0+0 (0x125) normal (normal left inverted right x axis y axis) 0mm x 0mm
DP-3 disconnected 1920x1080+3440+0 (0x126) normal (normal left inverted right x axis y axis) 0mm x 0mm
"""

CLEAN_XRANDR = """\
Screen 0: minimum 320 x 200, current 1920 x 1200, maximum 16384 x 16384
eDP-1 connected primary 1920x1200+0+0 (0x123) normal (normal left inverted right x axis y axis) 301mm x 188mm
  1920x1200 (0x124) 193.250MHz +HSync -VSync *current +preferred
DP-2 disconnected (normal left inverted right x axis y axis)
"""


def _fake_run(text: str):
    async def run(*args):
        return text

    return run


def test_parser_flags_disconnected_output_with_crtc_as_stale():
    outputs, stale = _parse_xrandr_verbose(GHOST_XRANDR)
    assert [o.connector for o in outputs] == ["eDP-1"]
    assert stale == ["DP-1"]


def test_cleanup_stale_turns_off_ghosts(monkeypatch):
    backend = XrandrBackend()
    calls: list[list[str]] = []

    async def fake_run_apply(args):
        calls.append(args)
        return True

    monkeypatch.setattr(xrandr_mod, "_run", _fake_run(TWO_GHOST_XRANDR))
    monkeypatch.setattr(xrandr_mod, "_run_apply", fake_run_apply)
    cleaned = asyncio.run(backend.cleanup_stale())
    assert cleaned == ["DP-1", "DP-3"]
    assert calls == [["--output", "DP-1", "--off", "--output", "DP-3", "--off"]]


def test_cleanup_stale_noop_without_ghosts(monkeypatch):
    backend = XrandrBackend()

    async def fail_run_apply(args):
        raise AssertionError("xrandr must not be invoked when nothing is stale")

    monkeypatch.setattr(xrandr_mod, "_run", _fake_run(CLEAN_XRANDR))
    monkeypatch.setattr(xrandr_mod, "_run_apply", fail_run_apply)
    assert asyncio.run(backend.cleanup_stale()) == []


def test_cleanup_stale_failure_keeps_ghosts(monkeypatch):
    backend = XrandrBackend()
    ok = False

    async def fake_run_apply(args):
        return ok

    monkeypatch.setattr(xrandr_mod, "_run", _fake_run(GHOST_XRANDR))
    monkeypatch.setattr(xrandr_mod, "_run_apply", fake_run_apply)
    assert asyncio.run(backend.cleanup_stale()) == []
    # The ghost is re-detected from a fresh read on the next attempt.
    ok = True
    assert asyncio.run(backend.cleanup_stale()) == ["DP-1"]


def test_apply_never_offs_outputs_it_was_not_asked_about(monkeypatch):
    """A ghost recorded by an earlier topology read must not be turned off by
    an unrelated apply -- the output may have been replugged since."""
    backend = XrandrBackend()
    calls: list[list[str]] = []

    async def fake_run_apply(args):
        calls.append(args)
        return True

    monkeypatch.setattr(xrandr_mod, "_run", _fake_run(GHOST_XRANDR))
    monkeypatch.setattr(xrandr_mod, "_run_apply", fake_run_apply)
    asyncio.run(backend.get_topology())

    cfg = OutputConfig(
        identity=MonitorIdentity("AUO", "panel", "1"), mode="1920x1200"
    )
    asyncio.run(backend.apply([("eDP-1", cfg)]))
    assert len(calls) == 1
    assert "--off" not in calls[0]
    assert "DP-1" not in calls[0]


class GhostBackend(DisplayBackend):
    def __init__(self) -> None:
        self.stale = ["DP-1"]
        self.cleanup_calls = 0
        self.topology = Topology(
            outputs=(
                ConnectedOutput(
                    connector="eDP-1",
                    identity=MonitorIdentity("AUO", "panel", "1"),
                    modes=("1920x1200",),
                    current_mode="1920x1200",
                    is_primary=True,
                ),
            )
        )

    async def get_topology(self) -> Topology:
        return self.topology

    async def apply(self, changes: list[tuple[str, OutputConfig]]) -> bool:
        return True

    async def verify(self, changes: list[tuple[str, OutputConfig]]) -> bool:
        return True

    def session_type(self) -> str:
        return "fake"

    async def cleanup_stale(self) -> list[str]:
        self.cleanup_calls += 1
        stale, self.stale = self.stale, []
        return stale


def test_reconcile_cleans_ghosts_even_without_matching_profile():
    backend = GhostBackend()
    applier = DisplayApplier(backend=backend, profiles=[])
    result = asyncio.run(applier.reconcile(force=True))
    assert backend.cleanup_calls == 1
    assert result is False  # still no profile to apply


def test_reconcile_cleans_ghosts_before_unchanged_state_short_circuit():
    backend = GhostBackend()
    applier = DisplayApplier(backend=backend, profiles=[])
    applier._last_applied_hash = backend.topology.full_state_hash
    result = asyncio.run(applier.reconcile(force=False))
    assert backend.cleanup_calls == 1
    assert result is True


def test_reconcile_cleans_ghosts_during_manual_cooldown():
    """The cooldown suppresses profile application, not hardware hygiene: a
    ghost CRTC left in place blocks Type-C replug for the whole window."""
    backend = GhostBackend()
    applier = DisplayApplier(backend=backend, profiles=[], cooldown_seconds=60)
    applier.cooldown.record_manual_change()
    result = asyncio.run(applier.reconcile(force=False))
    assert backend.cleanup_calls == 1
    assert result is False  # the apply itself stays suppressed


def test_cleanup_ghosts_runs_without_reconciling():
    """Used by the engine while auto-apply is paused."""
    backend = GhostBackend()
    applier = DisplayApplier(backend=backend, profiles=[])
    cleaned = asyncio.run(applier.cleanup_ghosts())
    assert cleaned == ["DP-1"]
    assert backend.cleanup_calls == 1
