"""Tests for xrandr --verbose output parsing: mode-name shapes and scale."""

from __future__ import annotations

import asyncio

import pytest

import displayd.backends.xrandr as xrandr_mod
from displayd.backends.xrandr import _parse_xrandr_verbose

VERBOSE_SCALED = """\
Screen 0: minimum 320 x 200, current 5160 x 2160, maximum 16384 x 16384
DP-1 connected primary 3440x1440+0+0 (0x1c8) normal (normal left inverted right x axis y axis) 800mm x 340mm
	Transform:   1.500000 0.000000 0.000000
	             0.000000 1.500000 0.000000
	             0.000000 0.000000 1.000000
	            filter: bilinear
  3440x1440 (0x1c8) 319.750MHz +HSync -VSync *current +preferred
  2560x1440 (0x1c9) 241.500MHz +HSync -VSync
eDP-1 connected 1920x1200+3440+0 (0x12a) normal (normal left inverted right x axis y axis) 301mm x 188mm
	Transform:   1.000000 0.000000 0.000000
	             0.000000 1.000000 0.000000
	             0.000000 0.000000 1.000000
	            filter:\x20
  1920x1200 (0x12b) 193.250MHz +HSync -VSync *current +preferred
"""

VERBOSE_INTERLACED = """\
Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 16384 x 16384
HDMI-1 connected 1920x1080+0+0 (0x1b2) normal (normal left inverted right x axis y axis) 1600mm x 900mm
  1920x1080i (0x1b3) 74.250MHz +HSync +VSync Interlace *current +preferred
  1920x1080 (0x1b4) 148.500MHz +HSync +VSync
  1920x1080_60.00 (0x2ff) 173.000MHz -HSync +VSync
"""

SIMPLE_INTERLACED = """\
Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 16384 x 16384
HDMI-1 connected 1920x1080+0+0 left (normal left inverted right x axis y axis) 509mm x 286mm
   1920x1080i    60.00*+  50.00
   1280x720      60.00
"""


def test_transform_scale_is_parsed():
    outputs, _ = _parse_xrandr_verbose(VERBOSE_SCALED)
    by_name = {o.connector: o for o in outputs}
    assert by_name["DP-1"].current_scale == 1.5
    assert by_name["eDP-1"].current_scale == 1.0


def test_scaled_output_keeps_mode_and_position():
    outputs, _ = _parse_xrandr_verbose(VERBOSE_SCALED)
    by_name = {o.connector: o for o in outputs}
    assert by_name["DP-1"].current_mode == "3440x1440"
    assert by_name["eDP-1"].current_position == (3440, 0)


def test_interlaced_and_custom_mode_names_are_parsed():
    outputs, _ = _parse_xrandr_verbose(VERBOSE_INTERLACED)
    (out,) = outputs
    assert out.current_mode == "1920x1080i"
    assert "1920x1080" in out.modes
    assert "1920x1080_60.00" in out.modes


def test_simple_format_mode_suffixes_are_parsed():
    outputs, _ = _parse_xrandr_verbose(SIMPLE_INTERLACED)
    (out,) = outputs
    assert out.current_mode == "1920x1080i"
    assert out.modes == ("1920x1080i", "1280x720")
    assert out.current_rotation == "left"


VERBOSE_SPACED_MODE = """\
Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 16384 x 16384
HDMI-1 connected 1920x1080+0+0 (0x1b2) normal (normal left inverted right x axis y axis) 1600mm x 900mm
  my custom mode (0x2ba) 173.000MHz -HSync +VSync *current
  1920x1080 (0x1b4) 148.500MHz +HSync +VSync
"""


def test_newmode_names_with_spaces_are_parsed():
    outputs, _ = _parse_xrandr_verbose(VERBOSE_SPACED_MODE)
    (out,) = outputs
    assert out.current_mode == "my custom mode"
    assert "1920x1080" in out.modes


def test_run_raises_on_nonzero_exit(monkeypatch):
    """A failed xrandr read must look like a failure upstream, not like a
    topology with zero outputs (which would defeat the applier's retries)."""

    class FakeProc:
        returncode = 1

        async def communicate(self):
            return b"", b"Can't open display :0"

    async def fake_exec(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(
        xrandr_mod.asyncio, "create_subprocess_exec", fake_exec
    )
    with pytest.raises(RuntimeError, match="Can't open display"):
        asyncio.run(xrandr_mod._run("--verbose", "--props"))
