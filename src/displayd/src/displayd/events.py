"""Event coalescing / debouncing for rapid-fire display events."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from .types import DisplayEvent, EventKind

log = logging.getLogger(__name__)

HARDWARE_EVENTS = frozenset(
    {
        EventKind.DRM_CHANGE,
        EventKind.DRM_ADD,
        EventKind.DRM_REMOVE,
        EventKind.RESUME,
        EventKind.LID_OPEN,
        EventKind.LID_CLOSE,
    }
)


class EventCoalescer:
    """Collects display events and fires a single coalesced callback after a
    quiet period, so dock/resume event storms produce at most one reconcile."""

    def __init__(
        self,
        debounce_seconds: float = 2.0,
        hardware_settle_seconds: float = 3.0,
    ) -> None:
        self._debounce = debounce_seconds
        self._hw_settle = hardware_settle_seconds
        self._pending: list[DisplayEvent] = []
        self._timer: Optional[asyncio.TimerHandle] = None
        self._callback: Optional[Callable[[list[DisplayEvent]], Awaitable[None]]] = None
        self._lock = asyncio.Lock()

    def set_callback(
        self, callback: Callable[[list[DisplayEvent]], Awaitable[None]]
    ) -> None:
        self._callback = callback

    async def push(self, event: DisplayEvent) -> None:
        async with self._lock:
            self._pending.append(event)
            log.debug("Event queued: %s (%s)", event.kind.name, event.detail)

            if self._timer is not None:
                self._timer.cancel()

            delay = (
                self._hw_settle
                if event.kind in HARDWARE_EVENTS
                else self._debounce
            )
            loop = asyncio.get_running_loop()
            self._timer = loop.call_later(delay, self._schedule_flush)

    def _schedule_flush(self) -> None:
        asyncio.ensure_future(self._flush())

    async def _flush(self) -> None:
        async with self._lock:
            if not self._pending:
                return
            batch = list(self._pending)
            self._pending.clear()
            self._timer = None

        kinds = {e.kind.name for e in batch}
        log.info("Coalesced %d event(s): %s", len(batch), ", ".join(sorted(kinds)))

        if self._callback is not None:
            try:
                await self._callback(batch)
            except Exception:
                log.exception("Error in coalesced-event callback")

    @property
    def pending_count(self) -> int:
        return len(self._pending)
