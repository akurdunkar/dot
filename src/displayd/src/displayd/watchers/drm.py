"""DRM/udev hotplug watcher -- asyncio integration via file-descriptor polling."""

from __future__ import annotations

import asyncio
import logging

import pyudev

from ..types import DisplayEvent, EventKind

log = logging.getLogger(__name__)

_ACTION_MAP: dict[str | None, EventKind] = {
    "change": EventKind.DRM_CHANGE,
    "add": EventKind.DRM_ADD,
    "remove": EventKind.DRM_REMOVE,
}


async def watch_drm(queue: asyncio.Queue[DisplayEvent]) -> None:
    """Poll udev for DRM subsystem events and enqueue them.

    Restarts the udev monitor after errors (e.g. netlink overruns during
    dock/resume event storms) instead of dying silently."""
    while True:
        try:
            await _watch_once(queue)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("DRM udev watcher error; restarting in 5 s")
        await asyncio.sleep(5)


async def _watch_once(queue: asyncio.Queue[DisplayEvent]) -> None:
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem="drm")
    monitor.start()

    loop = asyncio.get_running_loop()
    fd = monitor.fileno()
    log.info("Watching DRM subsystem via udev (fd=%d)", fd)

    while True:
        await _wait_readable(loop, fd)
        device = monitor.poll(timeout=0)
        if device is None:
            continue
        kind = _ACTION_MAP.get(device.action)
        if kind is None:
            continue
        log.debug("DRM %s: %s", device.action, device.device_path)
        await queue.put(DisplayEvent(kind=kind, detail=device.device_path))


async def _wait_readable(loop: asyncio.AbstractEventLoop, fd: int) -> None:
    fut: asyncio.Future[None] = loop.create_future()

    def _ready() -> None:
        if not fut.done():
            fut.set_result(None)

    loop.add_reader(fd, _ready)
    try:
        await fut
    finally:
        loop.remove_reader(fd)
