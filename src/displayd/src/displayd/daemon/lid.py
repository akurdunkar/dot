"""Lid switch watcher via evdev -- uses the native async_read_loop."""

from __future__ import annotations

import asyncio
import logging

import evdev
from evdev import ecodes

from ..types import DisplayEvent, EventKind

log = logging.getLogger(__name__)


def find_lid_switch() -> evdev.InputDevice | None:
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        caps = dev.capabilities()
        if ecodes.EV_SW in caps and ecodes.SW_LID in caps[ecodes.EV_SW]:
            return dev
    return None


async def watch_lid(queue: asyncio.Queue[DisplayEvent]) -> None:
    """Watch for lid open/close events and enqueue them."""
    device = find_lid_switch()
    if device is None:
        log.warning("No lid switch found; lid events disabled")
        return

    log.info("Watching lid switch: %s (%s)", device.path, device.name)
    async for event in device.async_read_loop():
        if event.type == ecodes.EV_SW and event.code == ecodes.SW_LID:
            kind = EventKind.LID_CLOSE if event.value else EventKind.LID_OPEN
            state = "closed" if event.value else "opened"
            log.debug("Lid %s", state)
            await queue.put(DisplayEvent(kind=kind, detail=state))
