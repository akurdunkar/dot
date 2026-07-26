"""Tests for xrandr apply-argument construction."""

from __future__ import annotations

from dataclasses import replace

from displayd.backends.xrandr import _build_apply_args
from displayd.types import MonitorIdentity, OutputConfig

IDENTITY = MonitorIdentity("DEL", "U2720Q", "SN123")

BASE_CFG = OutputConfig(
    identity=IDENTITY,
    enabled=True,
    mode="1920x1080",
    position=(0, 0),
    rotation="normal",
    primary=False,
)


def _cfg(**kwargs) -> OutputConfig:
    return replace(BASE_CFG, **kwargs)


def test_rotate_normal_is_always_passed():
    args = _build_apply_args([("DP-1", _cfg(rotation="normal"))])
    idx = args.index("--rotate")
    assert args[idx + 1] == "normal"


def test_rotate_left_is_passed():
    args = _build_apply_args([("DP-1", _cfg(rotation="left"))])
    idx = args.index("--rotate")
    assert args[idx + 1] == "left"


def test_disabled_output_gets_off_and_nothing_else():
    args = _build_apply_args([("DP-1", _cfg(enabled=False))])
    assert args == ["--output", "DP-1", "--off"]


def test_scale_one_is_always_passed():
    """Like --rotate normal: omitting --scale would leave a previously
    scaled output scaled, and verification would then fail forever."""
    args = _build_apply_args([("DP-1", _cfg(scale=1.0))])
    idx = args.index("--scale")
    assert args[idx + 1] == "1.0x1.0"


def test_full_argument_set():
    cfg = _cfg(mode="3840x2160", position=(1920, 0), primary=True, scale=1.5)
    args = _build_apply_args([("HDMI-1", cfg)])
    assert args == [
        "--output",
        "HDMI-1",
        "--mode",
        "3840x2160",
        "--pos",
        "1920x0",
        "--rotate",
        "normal",
        "--primary",
        "--scale",
        "1.5x1.5",
    ]


def test_enabled_output_without_explicit_scale_resets_to_one():
    args = _build_apply_args([("DP-1", _cfg())])
    idx = args.index("--scale")
    assert args[idx + 1] == "1.0x1.0"
