"""Main watcher daemon -- event intake, coalescing, agent notification via Unix socket."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from pathlib import Path

from ..events import EventCoalescer
from ..topology import read_lid_state, read_sysfs_topology
from ..types import DisplayEvent, EventKind
from .drm import watch_drm
from .lid import watch_lid
from .logind import watch_logind

log = logging.getLogger(__name__)

SOCKET_DIR = Path(os.environ.get("DISPLAYD_RUNTIME_DIR", "/run/displayd"))
SOCKET_PATH = SOCKET_DIR / "events.sock"


class WatcherDaemon:
    """System-level daemon that detects hardware/session events and notifies
    per-user session agents through a Unix socket."""

    def __init__(self, *, debounce: float = 2.0, settle: float = 3.0) -> None:
        self._event_queue: asyncio.Queue[DisplayEvent] = asyncio.Queue()
        self._coalescer = EventCoalescer(
            debounce_seconds=debounce,
            hardware_settle_seconds=settle,
        )
        self._agents: list[asyncio.StreamWriter] = []
        self._agents_lock = asyncio.Lock()
        self._last_topology_hash: str = ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        self._coalescer.set_callback(self._on_coalesced)

        tasks = [
            asyncio.create_task(self._pump_events(), name="event-pump"),
            asyncio.create_task(watch_drm(self._event_queue), name="drm"),
            asyncio.create_task(watch_lid(self._event_queue), name="lid"),
            asyncio.create_task(watch_logind(self._event_queue), name="logind"),
            asyncio.create_task(self._serve_agents(), name="agent-server"),
        ]

        await self._event_queue.put(
            DisplayEvent(kind=EventKind.STARTUP, detail="daemon started")
        )

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

        log.info("Watcher daemon running (socket=%s)", SOCKET_PATH)
        await stop.wait()
        log.info("Shutting down")

        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._cleanup_socket()

    # ------------------------------------------------------------------
    # Event pipeline
    # ------------------------------------------------------------------

    async def _pump_events(self) -> None:
        """Read raw events from the shared queue into the coalescer."""
        while True:
            event = await self._event_queue.get()
            await self._coalescer.push(event)

    async def _on_coalesced(self, events: list[DisplayEvent]) -> None:
        """Called after a quiet period; read topology and notify agents."""
        topology = read_sysfs_topology()
        lid = read_lid_state()
        topology = topology.__class__(outputs=topology.outputs, lid_closed=lid)

        current_hash = topology.identity_hash
        changed = current_hash != self._last_topology_hash
        self._last_topology_hash = current_hash

        notification = json.dumps(
            {
                "timestamp": time.time(),
                "events": [e.kind.name for e in events],
                "topology_hash": current_hash,
                "topology_changed": changed,
                "monitor_count": topology.monitor_count,
                "lid_closed": topology.lid_closed,
            }
        )
        log.info(
            "Topology hash=%s changed=%s monitors=%d lid_closed=%s",
            current_hash,
            changed,
            topology.monitor_count,
            topology.lid_closed,
        )
        await self._broadcast(notification)

    # ------------------------------------------------------------------
    # Agent socket server
    # ------------------------------------------------------------------

    async def _serve_agents(self) -> None:
        self._cleanup_socket()
        SOCKET_DIR.mkdir(parents=True, exist_ok=True)
        server = await asyncio.start_unix_server(
            self._handle_agent_conn, path=str(SOCKET_PATH)
        )
        os.chmod(SOCKET_PATH, 0o666)
        log.info("Agent socket ready at %s", SOCKET_PATH)
        async with server:
            await server.serve_forever()

    async def _handle_agent_conn(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        log.info("Agent connected")
        async with self._agents_lock:
            self._agents.append(writer)

        # Send current state so the agent doesn't miss events that
        # fired before it connected (e.g. STARTUP at boot).
        await self._send_current_state(writer)

        try:
            while True:
                data = await reader.read(1024)
                if not data:
                    break
        finally:
            async with self._agents_lock:
                if writer in self._agents:
                    self._agents.remove(writer)
            writer.close()
            log.info("Agent disconnected")

    async def _send_current_state(self, writer: asyncio.StreamWriter) -> None:
        topology = read_sysfs_topology()
        lid = read_lid_state()
        topology = topology.__class__(outputs=topology.outputs, lid_closed=lid)
        msg = json.dumps(
            {
                "timestamp": time.time(),
                "events": ["STARTUP"],
                "topology_hash": topology.identity_hash,
                "topology_changed": True,
                "monitor_count": topology.monitor_count,
                "lid_closed": topology.lid_closed,
            }
        )
        try:
            writer.write((msg + "\n").encode())
            await writer.drain()
        except (ConnectionError, OSError):
            pass

    async def _broadcast(self, message: str) -> None:
        line = (message + "\n").encode()
        async with self._agents_lock:
            stale: list[asyncio.StreamWriter] = []
            for writer in self._agents:
                try:
                    writer.write(line)
                    await writer.drain()
                except (ConnectionError, OSError):
                    stale.append(writer)
            for w in stale:
                self._agents.remove(w)
                try:
                    w.close()
                except OSError:
                    pass
            if stale:
                log.debug("Dropped %d stale agent connection(s)", len(stale))

    def _cleanup_socket(self) -> None:
        try:
            SOCKET_PATH.unlink(missing_ok=True)
        except OSError:
            pass
