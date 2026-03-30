"""``python -m displayd.agent`` -- launch the per-user session agent."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

from ..backends import detect_backend
from ..log import setup_logging
from ..policy import load_profiles
from .applier import DisplayApplier

log = logging.getLogger(__name__)

DEFAULT_PROFILE_DIR = Path(
    os.environ.get(
        "DISPLAYD_PROFILE_DIR",
        os.path.expanduser("~/.config/displayd/profiles"),
    )
)
SOCKET_PATH = (
    Path(os.environ.get("DISPLAYD_RUNTIME_DIR", "/run/displayd")) / "events.sock"
)

_ALWAYS_RECONCILE_EVENTS = frozenset(
    {"RESUME", "SESSION_UNLOCK", "SESSION_NEW", "STARTUP"}
)
_RESUME_EVENTS = frozenset({"RESUME", "LID_OPEN", "LID_CLOSE"})

STARTUP_SETTLE_SECONDS = 5.0
RESUME_SETTLE_SECONDS = 3.0


class SessionAgent:
    """Connects to the system watcher daemon's Unix socket and triggers
    display reconciliation on topology/session events."""

    def __init__(self, applier: DisplayApplier, socket_path: Path) -> None:
        self._applier = applier
        self._socket_path = socket_path

    async def run(self) -> None:
        log.info("Running initial reconciliation")
        await self._applier.reconcile(force=True)

        # Schedule a second reconciliation after a delay to catch late
        # display-server configuration that happens after the agent starts
        # (e.g. dwm/X11 turning on eDP after login).
        asyncio.get_running_loop().call_later(
            STARTUP_SETTLE_SECONDS,
            lambda: asyncio.ensure_future(self._deferred_reconcile()),
        )

        while True:
            try:
                await self._connect_and_listen()
            except (ConnectionError, OSError) as exc:
                log.warning("Daemon connection lost (%s); retrying in 5 s", exc)
                await asyncio.sleep(5)
            except Exception:
                log.exception("Unexpected error; retrying in 10 s")
                await asyncio.sleep(10)

    async def _deferred_reconcile(self) -> None:
        log.info("Deferred post-startup reconciliation")
        await self._applier.reconcile(force=True)

    async def _connect_and_listen(self) -> None:
        log.info("Connecting to daemon at %s", self._socket_path)
        reader, writer = await asyncio.open_unix_connection(str(self._socket_path))
        log.info("Connected to daemon")

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break

                try:
                    note = json.loads(line)
                except json.JSONDecodeError:
                    log.warning(
                        "Bad notification: %s", line.decode(errors="replace").strip()
                    )
                    continue

                events = note.get("events", [])
                topo_changed = note.get("topology_changed", True)
                log.info(
                    "Notification: events=%s topo_changed=%s",
                    events,
                    topo_changed,
                )

                if topo_changed or _ALWAYS_RECONCILE_EVENTS & set(events):
                    if _RESUME_EVENTS & set(events):
                        log.info(
                            "Resume/lid event -- waiting %.0f s for display to stabilize",
                            RESUME_SETTLE_SECONDS,
                        )
                        await asyncio.sleep(RESUME_SETTLE_SECONDS)
                    await self._applier.reconcile(force=True)
        finally:
            writer.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="displayd session agent")
    ap.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Profile directory (default: %(default)s)",
    )
    ap.add_argument(
        "--socket",
        type=Path,
        default=SOCKET_PATH,
        help="Daemon socket path (default: %(default)s)",
    )
    ap.add_argument(
        "--cooldown",
        type=float,
        default=30.0,
        help="Manual-change cooldown seconds (default: %(default)s)",
    )
    ap.add_argument(
        "--retries", type=int, default=5, help="Max apply retries (default: %(default)s)"
    )
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--json-log", action="store_true")
    args = ap.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging("displayd", level=level, json_format=args.json_log)

    backend = detect_backend()
    profiles = load_profiles(args.profile_dir)
    log.info("Loaded %d profile(s) from %s", len(profiles), args.profile_dir)
    log.info("Backend: %s", type(backend).__name__)

    applier = DisplayApplier(
        backend=backend,
        profiles=profiles,
        max_retries=args.retries,
        cooldown_seconds=args.cooldown,
    )
    agent = SessionAgent(applier, args.socket)
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
