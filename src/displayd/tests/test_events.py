"""Tests for event coalescing / debouncing."""

from __future__ import annotations

import asyncio

import pytest

from displayd.events import EventCoalescer
from displayd.types import DisplayEvent, EventKind


@pytest.mark.asyncio
class TestEventCoalescer:
    async def test_single_event_fires_after_debounce(self):
        results: list[list[DisplayEvent]] = []

        async def cb(events: list[DisplayEvent]) -> None:
            results.append(events)

        c = EventCoalescer(debounce_seconds=0.1, hardware_settle_seconds=0.1)
        c.set_callback(cb)

        await c.push(DisplayEvent(kind=EventKind.STARTUP, detail="test"))
        assert len(results) == 0

        await asyncio.sleep(0.25)
        assert len(results) == 1
        assert len(results[0]) == 1
        assert results[0][0].kind is EventKind.STARTUP

    async def test_burst_coalesces_into_one_callback(self):
        results: list[list[DisplayEvent]] = []

        async def cb(events: list[DisplayEvent]) -> None:
            results.append(events)

        c = EventCoalescer(debounce_seconds=0.2, hardware_settle_seconds=0.2)
        c.set_callback(cb)

        for i in range(5):
            await c.push(DisplayEvent(kind=EventKind.DRM_CHANGE, detail=str(i)))
            await asyncio.sleep(0.03)

        assert len(results) == 0
        await asyncio.sleep(0.4)
        assert len(results) == 1
        assert len(results[0]) == 5

    async def test_separate_bursts_fire_independently(self):
        results: list[list[DisplayEvent]] = []

        async def cb(events: list[DisplayEvent]) -> None:
            results.append(events)

        c = EventCoalescer(debounce_seconds=0.1, hardware_settle_seconds=0.1)
        c.set_callback(cb)

        await c.push(DisplayEvent(kind=EventKind.DRM_CHANGE, detail="a"))
        await asyncio.sleep(0.25)
        assert len(results) == 1

        await c.push(DisplayEvent(kind=EventKind.DRM_CHANGE, detail="b"))
        await asyncio.sleep(0.25)
        assert len(results) == 2

    async def test_hardware_events_use_longer_settle(self):
        results: list[list[DisplayEvent]] = []

        async def cb(events: list[DisplayEvent]) -> None:
            results.append(events)

        c = EventCoalescer(debounce_seconds=0.05, hardware_settle_seconds=0.3)
        c.set_callback(cb)

        await c.push(DisplayEvent(kind=EventKind.DRM_CHANGE, detail="hw"))
        await asyncio.sleep(0.1)
        assert len(results) == 0  # still waiting (0.3 s settle)

        await asyncio.sleep(0.35)
        assert len(results) == 1

    async def test_pending_count(self):
        c = EventCoalescer(debounce_seconds=5.0, hardware_settle_seconds=5.0)
        c.set_callback(lambda _: asyncio.sleep(0))

        assert c.pending_count == 0
        await c.push(DisplayEvent(kind=EventKind.STARTUP))
        assert c.pending_count == 1
        await c.push(DisplayEvent(kind=EventKind.DRM_CHANGE))
        assert c.pending_count == 2

    async def test_no_callback_does_not_crash(self):
        c = EventCoalescer(debounce_seconds=0.05, hardware_settle_seconds=0.05)
        await c.push(DisplayEvent(kind=EventKind.STARTUP))
        await asyncio.sleep(0.15)  # flush fires but callback is None
