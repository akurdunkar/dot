"""Logind D-Bus signal listener -- replaces dbus-monitor subprocess parsing.

Listens on the system bus for:
  - org.freedesktop.login1.Manager.PrepareForSleep  (resume detection)
  - org.freedesktop.login1.Session.Unlock            (screen unlock)
  - org.freedesktop.login1.Manager.SessionNew         (new login session)

Automatically reconnects on D-Bus disconnection.
"""

from __future__ import annotations

import asyncio
import logging

from dbus_fast import BusType, Message
from dbus_fast.aio import MessageBus

from ..types import DisplayEvent, EventKind

log = logging.getLogger(__name__)

_MATCH_RULES = [
    (
        "type='signal',"
        "interface='org.freedesktop.login1.Manager',"
        "member='PrepareForSleep'"
    ),
    (
        "type='signal',"
        "interface='org.freedesktop.login1.Session',"
        "member='Unlock'"
    ),
    (
        "type='signal',"
        "interface='org.freedesktop.login1.Manager',"
        "member='SessionNew'"
    ),
]


async def watch_logind(queue: asyncio.Queue[DisplayEvent]) -> None:
    """Connect to the system bus and forward logind signals.  Reconnects on error."""
    while True:
        try:
            await _watch_once(queue)
        except Exception:
            log.exception("logind listener error; reconnecting in 5 s")
        await asyncio.sleep(5)


async def _watch_once(queue: asyncio.Queue[DisplayEvent]) -> None:
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    log.info("Connected to system D-Bus for logind signals")

    try:
        for rule in _MATCH_RULES:
            await bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="AddMatch",
                    signature="s",
                    body=[rule],
                )
            )

        def _on_message(msg: Message) -> None:
            iface = msg.interface or ""
            member = msg.member or ""

            if iface == "org.freedesktop.login1.Manager":
                if member == "PrepareForSleep":
                    going_to_sleep = msg.body[0] if msg.body else True
                    if not going_to_sleep:
                        log.info("System resumed from sleep")
                        asyncio.ensure_future(
                            queue.put(
                                DisplayEvent(
                                    kind=EventKind.RESUME,
                                    detail="system resumed",
                                )
                            )
                        )
                elif member == "SessionNew":
                    sid = str(msg.body[0]) if msg.body else "?"
                    log.info("New logind session: %s", sid)
                    asyncio.ensure_future(
                        queue.put(
                            DisplayEvent(kind=EventKind.SESSION_NEW, detail=sid)
                        )
                    )

            elif iface == "org.freedesktop.login1.Session":
                if member == "Unlock":
                    log.info("Session unlocked")
                    asyncio.ensure_future(
                        queue.put(
                            DisplayEvent(
                                kind=EventKind.SESSION_UNLOCK,
                                detail="session unlocked",
                            )
                        )
                    )

        bus.add_message_handler(_on_message)
        await bus.wait_for_disconnect()
    finally:
        bus.disconnect()

    log.warning("System D-Bus connection lost")
