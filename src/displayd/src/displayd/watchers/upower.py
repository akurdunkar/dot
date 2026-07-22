"""UPower lid-switch watcher -- D-Bus PropertiesChanged on LidIsClosed.

Reads the initial lid state from org.freedesktop.UPower and then forwards
every lid transition as a LID_OPEN / LID_CLOSE event.  The current state is
also reported through a callback so the engine can keep its lid-aware
topology hashing up to date.

Automatically reconnects on D-Bus disconnection.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from dbus_fast import BusType, Message, MessageType
from dbus_fast.aio import MessageBus

from ..types import DisplayEvent, EventKind

log = logging.getLogger(__name__)

_UPOWER_NAME = "org.freedesktop.UPower"
_UPOWER_PATH = "/org/freedesktop/UPower"
_PROPS_IFACE = "org.freedesktop.DBus.Properties"

_MATCH_RULE = (
    "type='signal',"
    f"interface='{_PROPS_IFACE}',"
    "member='PropertiesChanged',"
    f"path='{_UPOWER_PATH}',"
    f"sender='{_UPOWER_NAME}'"
)


async def watch_lid_upower(
    queue: asyncio.Queue[DisplayEvent],
    on_state: Callable[[bool], None],
) -> None:
    """Watch UPower's LidIsClosed property.  Reconnects on error."""
    while True:
        try:
            present = await _watch_once(queue, on_state)
            if not present:
                return
        except Exception:
            log.exception("UPower lid listener error; reconnecting in 5 s")
        await asyncio.sleep(5)


async def _get_property(bus: MessageBus, prop: str) -> object:
    reply = await bus.call(
        Message(
            destination=_UPOWER_NAME,
            path=_UPOWER_PATH,
            interface=_PROPS_IFACE,
            member="Get",
            signature="ss",
            body=[_UPOWER_NAME, prop],
        )
    )
    if reply is None or reply.message_type == MessageType.ERROR:
        detail = reply.body[0] if reply is not None and reply.body else "no reply"
        raise RuntimeError(f"UPower Get({prop}) failed: {detail}")
    return reply.body[0].value


async def _watch_once(
    queue: asyncio.Queue[DisplayEvent],
    on_state: Callable[[bool], None],
) -> bool:
    """Returns False when UPower has no lid to watch (caller should give up)."""
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

    try:
        try:
            lid_present = bool(await _get_property(bus, "LidIsPresent"))
        except RuntimeError as exc:
            log.warning("UPower unavailable; lid watching disabled (%s)", exc)
            return False

        if not lid_present:
            log.warning("UPower reports no lid; lid watching disabled")
            return False

        lid_closed = bool(await _get_property(bus, "LidIsClosed"))
        log.info(
            "Connected to UPower; lid is %s", "closed" if lid_closed else "open"
        )
        on_state(lid_closed)

        await bus.call(
            Message(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="AddMatch",
                signature="s",
                body=[_MATCH_RULE],
            )
        )

        last_state = lid_closed

        def _on_message(msg: Message) -> None:
            nonlocal last_state
            if (
                msg.interface != _PROPS_IFACE
                or msg.member != "PropertiesChanged"
                or msg.path != _UPOWER_PATH
                or len(msg.body) < 2
                or msg.body[0] != _UPOWER_NAME
            ):
                return
            changed = msg.body[1]
            if "LidIsClosed" not in changed:
                return
            closed = bool(changed["LidIsClosed"].value)
            if closed == last_state:
                return
            last_state = closed
            log.info("Lid %s", "closed" if closed else "opened")
            on_state(closed)
            kind = EventKind.LID_CLOSE if closed else EventKind.LID_OPEN
            detail = "lid closed" if closed else "lid opened"
            asyncio.ensure_future(queue.put(DisplayEvent(kind=kind, detail=detail)))

        bus.add_message_handler(_on_message)
        await bus.wait_for_disconnect()
    finally:
        bus.disconnect()

    log.warning("System D-Bus connection lost")
    return True
