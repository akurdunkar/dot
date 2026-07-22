"""X11/XRandR display backend -- the fully-implemented reference backend.

Reads topology (including EDID-based identity) via ``xrandr --verbose --props``
and applies changes via ``xrandr --output ... --mode ... --pos ...``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from ..topology import parse_edid
from ..types import (
    ConnectedOutput,
    OutputConfig,
    Topology,
    UNKNOWN_IDENTITY,
)
from .base import DisplayBackend

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# xrandr output parser
# ---------------------------------------------------------------------------

_OUTPUT_HEADER = re.compile(
    r"^(\S+)\s+(connected|disconnected)\s*"
    r"(?:(primary)\s+)?"
    r"(?:(\d+)x(\d+)\+(\d+)\+(\d+)\s*)?"
    r"(?:\(0x[0-9a-fA-F]+\)\s*)?"
    r"(?:(left|right|inverted|normal)\s+)?"
)
# Verbose: "  3440x1440 (0x6a6) 319.750MHz +HSync -VSync *current +preferred"
_MODE_LINE_VERBOSE = re.compile(r"^\s+(\d+x\d+)\s+\(0x[0-9a-fA-F]+\)\s+[\d.]+MHz\b(.*)")
# Non-verbose: "  3440x1440     59.97*+  29.99"
_MODE_LINE_SIMPLE = re.compile(r"^\s+(\d+x\d+)\s+([\d.]+)(\*?)(\+?)")
_EDID_TAG = re.compile(r"^\s+EDID:\s*$")
_HEX_LINE = re.compile(r"^\s+([0-9a-fA-F]+)\s*$")


def _parse_xrandr_verbose(
    text: str,
) -> tuple[list[ConnectedOutput], list[str]]:
    """Parse ``xrandr --verbose --props``.

    Returns (connected_outputs, stale_disconnected_names) where
    stale_disconnected_names lists disconnected outputs that still have
    a CRTC/mode assigned (ghost outputs that need ``--off``).
    """
    results: list[ConnectedOutput] = []
    stale: list[str] = []

    name: Optional[str] = None
    connected = False
    primary = False
    has_geometry = False
    cur_mode: Optional[str] = None
    cur_pos = (0, 0)
    cur_rotation = "normal"
    modes: list[str] = []
    edid_hex = ""
    in_edid = False

    def _flush() -> None:
        nonlocal name, connected, primary, has_geometry, cur_mode, cur_pos
        nonlocal cur_rotation, modes, edid_hex, in_edid
        if name and connected:
            identity = UNKNOWN_IDENTITY
            edid_raw = b""
            if edid_hex:
                try:
                    edid_raw = bytes.fromhex(edid_hex)
                    identity = parse_edid(edid_raw)
                except ValueError:
                    pass
            results.append(
                ConnectedOutput(
                    connector=name,
                    identity=identity,
                    modes=tuple(modes),
                    current_mode=cur_mode,
                    current_position=cur_pos,
                    current_rotation=cur_rotation,
                    is_primary=primary,
                    edid_raw=edid_raw,
                )
            )
        elif name and not connected and has_geometry:
            stale.append(name)
        name = None
        connected = False
        primary = False
        has_geometry = False
        cur_mode = None
        cur_pos = (0, 0)
        cur_rotation = "normal"
        modes = []
        edid_hex = ""
        in_edid = False

    for line in text.splitlines():
        hdr = _OUTPUT_HEADER.match(line)
        if hdr:
            _flush()
            name = hdr.group(1)
            connected = hdr.group(2) == "connected"
            primary = hdr.group(3) == "primary"
            if hdr.group(4) and hdr.group(5):
                has_geometry = True
                cur_pos = (int(hdr.group(6) or 0), int(hdr.group(7) or 0))
            if hdr.group(8):
                cur_rotation = hdr.group(8)
            continue

        if _EDID_TAG.match(line):
            in_edid = True
            edid_hex = ""
            continue

        if in_edid:
            hm = _HEX_LINE.match(line)
            if hm:
                edid_hex += hm.group(1)
            else:
                in_edid = False

        mv = _MODE_LINE_VERBOSE.match(line)
        if mv and name:
            mode = mv.group(1)
            flags = mv.group(2)
            if mode not in modes:
                modes.append(mode)
            if "*current" in flags:
                cur_mode = mode
            continue

        ms = _MODE_LINE_SIMPLE.match(line)
        if ms and name:
            mode = ms.group(1)
            if mode not in modes:
                modes.append(mode)
            if "*" in ms.group(3):
                cur_mode = mode

    _flush()
    return results, stale


# ---------------------------------------------------------------------------
# Backend implementation
# ---------------------------------------------------------------------------


class XrandrBackend(DisplayBackend):
    def __init__(self) -> None:
        self._stale_outputs: list[str] = []

    def session_type(self) -> str:
        return "x11"

    async def get_topology(self) -> Topology:
        stdout = await _run("--verbose", "--props")
        outputs, self._stale_outputs = _parse_xrandr_verbose(stdout)
        return Topology(outputs=tuple(outputs))

    async def apply(self, changes: list[tuple[str, OutputConfig]]) -> bool:
        args = _build_apply_args(changes)

        # Turn off disconnected outputs that still hold a CRTC (ghost outputs)
        for stale_name in self._stale_outputs:
            if not any(c == stale_name for c, _ in changes):
                log.info("Cleaning up stale disconnected output %s", stale_name)
                args.extend(["--output", stale_name, "--off"])

        if not args:
            return True
        return await _run_apply(args)

    async def cleanup_stale(self) -> list[str]:
        stale = list(self._stale_outputs)
        if not stale:
            return []
        args: list[str] = []
        for name in stale:
            args.extend(["--output", name, "--off"])
        log.info("Turning off stale disconnected output(s): %s", ", ".join(stale))
        if not await _run_apply(args):
            return []
        self._stale_outputs = []
        return stale

    async def verify(self, changes: list[tuple[str, OutputConfig]]) -> bool:
        topology = await self.get_topology()
        for connector, desired in changes:
            output = next(
                (o for o in topology.outputs if o.connector == connector), None
            )
            if output is None:
                log.warning("Verify: output %s disappeared", connector)
                return False
            if not desired.enabled:
                if output.current_mode is not None:
                    log.warning(
                        "Verify: %s should be off but has mode %s",
                        connector,
                        output.current_mode,
                    )
                    return False
            else:
                if desired.mode and output.current_mode != desired.mode:
                    log.warning(
                        "Verify: %s mode %s != desired %s",
                        connector,
                        output.current_mode,
                        desired.mode,
                    )
                    return False
                if output.current_position != desired.position:
                    log.warning(
                        "Verify: %s pos %s != desired %s",
                        connector,
                        output.current_position,
                        desired.position,
                    )
                    return False
                if output.current_rotation != desired.rotation:
                    log.warning(
                        "Verify: %s rotation %s != desired %s",
                        connector,
                        output.current_rotation,
                        desired.rotation,
                    )
                    return False
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_apply_args(changes: list[tuple[str, OutputConfig]]) -> list[str]:
    args: list[str] = []
    for connector, cfg in changes:
        args.extend(["--output", connector])
        if not cfg.enabled:
            args.append("--off")
            continue
        if cfg.mode:
            args.extend(["--mode", cfg.mode])
        args.extend(["--pos", f"{cfg.position[0]}x{cfg.position[1]}"])
        # Always pass --rotate: omitting it would leave a previously rotated
        # output rotated when the desired rotation is "normal".
        args.extend(["--rotate", cfg.rotation])
        if cfg.primary:
            args.append("--primary")
        if cfg.scale != 1.0:
            args.extend(["--scale", f"{cfg.scale}x{cfg.scale}"])
    return args


async def _run_apply(args: list[str]) -> bool:
    log.info("xrandr %s", " ".join(args))
    try:
        proc = await asyncio.create_subprocess_exec(
            "xrandr",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.error(
                "xrandr failed (rc=%d): %s",
                proc.returncode,
                stderr.decode(errors="replace"),
            )
            return False
        return True
    except FileNotFoundError:
        log.error("xrandr binary not found")
        return False


async def _run(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "xrandr",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        log.error(
            "xrandr %s failed (rc=%d): %s",
            " ".join(args),
            proc.returncode,
            stderr.decode(errors="replace"),
        )
    return stdout.decode(errors="replace")
