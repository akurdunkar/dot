"""Display-management engine: watchers, coalescing, and reconciliation on a
background asyncio thread, with a thread-safe API for the GTK main thread."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Optional

from .applier import DisplayApplier
from .backends import LidAwareBackend, detect_backend
from .backends.base import DisplayBackend
from .events import EventCoalescer
from .policy import (
    load_profiles,
    match_profile,
    plan_reconciliation,
    profile_matches_monitor_set,
    profiles_signature,
    save_profile,
    snapshot_to_profile,
)
from .topology import read_lid_state
from .types import DisplayEvent, EventKind, OutputConfig, Profile, Topology
from .watchers.drm import watch_drm
from .watchers.logind import watch_logind
from .watchers.upower import get_lid_closed, watch_lid_upower

log = logging.getLogger(__name__)

RESUME_SETTLE_SECONDS = 3.0
STARTUP_SETTLE_SECONDS = 5.0
PROFILE_POLL_SECONDS = 10.0

_RESUME_EVENTS = frozenset(
    {EventKind.RESUME, EventKind.LID_OPEN, EventKind.LID_CLOSE}
)


@dataclass(frozen=True)
class EngineState:
    topology: Optional[Topology]
    matched_profile: Optional[str]
    in_sync: bool
    paused: bool
    profiles: tuple[Profile, ...]


class Engine:
    """Owns the asyncio side of displayd on a daemon thread and exposes a
    thread-safe facade for UI code running on the GTK main thread."""

    def __init__(
        self,
        *,
        profile_dir: Path,
        cooldown: float = 30.0,
        retries: int = 5,
        debounce: float = 2.0,
        settle: float = 3.0,
        backend: Optional[DisplayBackend] = None,
        enable_watchers: bool = True,
    ) -> None:
        self._profile_dir = profile_dir
        self._enable_watchers = enable_watchers
        self._lock = threading.Lock()
        self._lid_closed = read_lid_state()

        inner = backend if backend is not None else detect_backend()
        self._backend = LidAwareBackend(inner, self._get_lid)

        self._profiles = load_profiles(profile_dir)
        self._profiles_signature = profiles_signature(profile_dir)
        self._applier = DisplayApplier(
            backend=self._backend,
            profiles=self._profiles,
            max_retries=retries,
            cooldown_seconds=cooldown,
        )

        self._queue: asyncio.Queue[DisplayEvent] = asyncio.Queue()
        self._coalescer = EventCoalescer(
            debounce_seconds=debounce,
            hardware_settle_seconds=settle,
        )
        self._coalescer.set_callback(self._on_coalesced)

        self._listeners: list[Callable[[EngineState], None]] = []
        self._paused = False
        self._state = EngineState(
            topology=None,
            matched_profile=None,
            in_sync=False,
            paused=False,
            profiles=tuple(self._profiles),
        )

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._cooldown_retry: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Engine already started")
        self._thread = threading.Thread(
            target=self._run_loop, name="displayd-engine", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=10):
            raise RuntimeError("Engine event loop failed to start")

    def stop(self) -> None:
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None or not thread.is_alive():
            return

        def _shutdown() -> None:
            for task in asyncio.all_tasks(loop):
                task.cancel()
            loop.stop()

        loop.call_soon_threadsafe(_shutdown)
        thread.join(timeout=5)

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        loop.call_soon(self._ready.set)
        loop.create_task(self._startup())
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.run_until_complete(loop.shutdown_asyncgens())
            asyncio.set_event_loop(None)
            loop.close()

    async def _startup(self) -> None:
        if self._enable_watchers:
            # Align the initial lid state with UPower (the live tracking
            # source) before the first reconcile; the /proc fallback used in
            # __init__ is absent on many machines and would hash a different
            # topology than the daemon settles on.
            try:
                self._set_lid(await get_lid_closed())
            except Exception:
                log.exception("Initial lid state read failed")

        self._spawn(self._consume_events(), "event-pump")
        if self._enable_watchers:
            self._spawn(watch_drm(self._queue), "drm")
            self._spawn(watch_logind(self._queue), "logind")
            self._spawn(watch_lid_upower(self._queue, self._set_lid), "upower-lid")
            self._spawn(self._watch_profile_dir(), "profile-watch")

        log.info("Initial reconciliation")
        try:
            await self._reconcile(force=True)
        except Exception:
            log.exception("Initial reconciliation failed")
        await self._refresh_state()
        self._spawn(self._deferred_reconcile(), "deferred-reconcile")

    def _spawn(self, coro, name: str) -> asyncio.Task:
        """Run a background task on the engine loop, logging any crash."""
        task = asyncio.ensure_future(coro)
        task.set_name(f"displayd-{name}")

        def _done(t: asyncio.Task) -> None:
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                log.error("Background task %r died", name, exc_info=exc)

        task.add_done_callback(_done)
        return task

    async def _deferred_reconcile(self) -> None:
        await asyncio.sleep(STARTUP_SETTLE_SECONDS)
        log.info("Deferred post-startup reconciliation")
        try:
            await self._reconcile(force=True)
        except Exception:
            log.exception("Deferred reconciliation failed")
        await self._refresh_state()

    async def _reconcile(self, *, force: bool) -> bool:
        """Reconcile via the applier, picking up on-disk profile edits first
        so out-of-band changes (displayd-ctl, hand edits) are honored."""
        try:
            await self._check_profiles_fresh()
        except Exception:
            log.exception("Profile freshness check failed")
        return await self._applier.reconcile(force=force)

    async def _check_profiles_fresh(self) -> bool:
        signature = profiles_signature(self._profile_dir)
        if signature == self._profiles_signature:
            return False
        log.info("Profile directory changed on disk; reloading profiles")
        self._load_profiles_from_disk()
        return True

    async def _watch_profile_dir(self) -> None:
        """Poll the profile directory so ctl-side saves/deletes reach the
        tray and matching without waiting for the next display event."""
        while True:
            await asyncio.sleep(PROFILE_POLL_SECONDS)
            try:
                if await self._check_profiles_fresh():
                    await self._refresh_state()
            except Exception:
                log.exception("Profile directory poll failed")

    async def _consume_events(self) -> None:
        while True:
            event = await self._queue.get()
            await self._coalescer.push(event)

    async def _on_coalesced(self, events: list[DisplayEvent]) -> None:
        if self.state.paused:
            log.info("Auto-apply paused; skipping %d event(s)", len(events))
            await self._applier.cleanup_ghosts()
            await self._refresh_state()
            return

        kinds = {e.kind for e in events}
        if kinds & _RESUME_EVENTS:
            log.info(
                "Resume/lid event -- waiting %.1f s for display to stabilize",
                RESUME_SETTLE_SECONDS,
            )
            await asyncio.sleep(RESUME_SETTLE_SECONDS)
            if self.state.paused:
                log.info("Auto-apply paused during settle; skipping")
                await self._applier.cleanup_ghosts()
                await self._refresh_state()
                return

        # force=False so the manual-change cooldown and the unchanged-state
        # short-circuit are honored; explicit "Sync now" still forces.
        try:
            await self._reconcile(force=False)
        except Exception:
            log.exception("Event-driven reconciliation failed")
        if self._applier.last_reconcile_suppressed:
            # The event is consumed but its work is not done; retry once the
            # cooldown ends or a dock during the window stays black forever.
            self._schedule_cooldown_retry()
        await self._refresh_state()

    def _schedule_cooldown_retry(self) -> None:
        if self._cooldown_retry is not None and not self._cooldown_retry.done():
            return
        remaining = self._applier.cooldown.remaining_seconds
        log.info(
            "Reconcile deferred %.1f s until the manual-change cooldown ends",
            remaining,
        )
        self._cooldown_retry = self._spawn(
            self._cooldown_retry_wait(remaining), "cooldown-retry"
        )

    async def _cooldown_retry_wait(self, delay: float) -> None:
        await asyncio.sleep(delay + 0.25)
        log.info("Cooldown expired; running deferred reconciliation")
        try:
            await self._reconcile(force=False)
        except Exception:
            log.exception("Deferred cooldown reconciliation failed")
        await self._refresh_state()
        self._cooldown_retry = None
        if self._applier.last_reconcile_suppressed:
            # A manual change landed while we slept (or an event's reconcile
            # was suppressed while we were finishing up); go around again.
            self._schedule_cooldown_retry()

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def state(self) -> EngineState:
        with self._lock:
            return self._state

    def add_state_listener(self, cb: Callable[[EngineState], None]) -> None:
        with self._lock:
            self._listeners.append(cb)

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = paused
            self._state = replace(self._state, paused=paused)
            state = self._state
        log.info("Auto-apply %s", "paused" if paused else "resumed")
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._notify_listeners, state)
            if not paused:
                # Events skipped while paused are gone; reconcile once so the
                # layout catches up with whatever changed in the meantime.
                # Via _spawn so a crash is logged, not silently swallowed.
                loop.call_soon_threadsafe(
                    lambda: self._spawn(
                        self._resume_reconcile(), "unpause-reconcile"
                    )
                )
        else:
            self._notify_listeners(state)

    async def _resume_reconcile(self) -> None:
        try:
            await self._reconcile(force=False)
        except Exception:
            log.exception("Post-unpause reconciliation failed")
        if self._applier.last_reconcile_suppressed:
            # The catch-up hit the manual-change cooldown; without a retry
            # the events dropped while paused would be lost after all.
            self._schedule_cooldown_retry()
        await self._refresh_state()

    def _get_lid(self) -> bool:
        with self._lock:
            return self._lid_closed

    def _set_lid(self, closed: bool) -> None:
        with self._lock:
            self._lid_closed = closed

    def _notify_listeners(self, state: EngineState) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(state)
            except Exception:
                log.exception("State listener raised")

    async def _refresh_state(self) -> None:
        topology: Optional[Topology] = None
        try:
            topology = await self._backend.get_topology()
        except Exception:
            log.exception("State refresh: topology read failed")

        with self._lock:
            profiles = list(self._profiles)

        matched: Optional[str] = None
        in_sync = False
        if topology is not None:
            # Prefer the profile the daemon last put on screen (tray switch,
            # snapshot, or auto-apply) over a pure priority match, so that
            # switching between profiles for the same monitor set is
            # reflected in the UI. Fall back to matching when the record is
            # stale (profile deleted or monitor set changed).
            profile: Optional[Profile] = None
            active = self._applier.last_profile
            if active is not None:
                profile = next(
                    (
                        p
                        for p in profiles
                        if p.name == active
                        and profile_matches_monitor_set(p, topology)
                    ),
                    None,
                )
            if profile is None:
                profile = match_profile(topology, profiles)
            if profile is not None:
                matched = profile.name
                in_sync = plan_reconciliation(topology, profile).is_noop

        with self._lock:
            self._state = EngineState(
                topology=topology,
                matched_profile=matched,
                in_sync=in_sync,
                paused=self._paused,
                profiles=tuple(profiles),
            )
            state = self._state
        self._notify_listeners(state)

    def _load_profiles_from_disk(self) -> None:
        # Signature first: a write landing mid-load then makes the stored
        # signature stale and the next freshness check reloads (self-healing);
        # the other order would stamp unseen content as already loaded.
        signature = profiles_signature(self._profile_dir)
        profiles = load_profiles(self._profile_dir)
        self._profiles_signature = signature
        with self._lock:
            self._profiles = profiles
        self._applier.reload_profiles(profiles)

    async def _reload_profiles(self) -> None:
        self._load_profiles_from_disk()
        await self._refresh_state()

    # ------------------------------------------------------------------
    # Thread-safe operations (callable from the GTK thread)
    # ------------------------------------------------------------------

    def inject_event(self, event: DisplayEvent) -> None:
        """Testing/diagnostic seam: enqueue an event as if a watcher saw it."""
        self._submit(self._queue.put(event))

    def get_topology(self) -> concurrent.futures.Future[Topology]:
        return self._submit(self._backend.get_topology())

    def sync_now(self) -> concurrent.futures.Future[bool]:
        return self._submit(self._sync_now())

    def apply_layout(
        self, changes: list[tuple[str, OutputConfig]]
    ) -> concurrent.futures.Future[bool]:
        return self._submit(self._apply_layout(changes))

    def apply_profile(self, name: str) -> concurrent.futures.Future[bool]:
        return self._submit(self._apply_profile(name))

    def save_layout(
        self,
        name: str,
        outputs: list[OutputConfig],
        topology_hash: str,
        priority: int = 0,
    ) -> concurrent.futures.Future[Path]:
        return self._submit(self._save_layout(name, outputs, topology_hash, priority))

    def snapshot_current(
        self, name: str, priority: int = 0
    ) -> concurrent.futures.Future[Path]:
        return self._submit(self._snapshot_current(name, priority))

    def delete_profile(self, name: str) -> concurrent.futures.Future[None]:
        return self._submit(self._delete_profile(name))

    def _submit(self, coro) -> concurrent.futures.Future:
        loop = self._loop
        if loop is None:
            raise RuntimeError("Engine not started")
        return asyncio.run_coroutine_threadsafe(coro, loop)

    async def _sync_now(self) -> bool:
        ok = await self._reconcile(force=True)
        await self._refresh_state()
        return ok

    async def _apply_layout(self, changes: list[tuple[str, OutputConfig]]) -> bool:
        ok = await self._applier.apply_manual(changes)
        await self._refresh_state()
        return ok

    async def _apply_profile(self, name: str) -> bool:
        with self._lock:
            profiles = list(self._profiles)
        profile = next((p for p in profiles if p.name == name), None)
        if profile is None:
            raise ValueError(f"No profile named {name!r}")
        topology = await self._backend.get_topology()
        # Applying a profile from a different monitor set could --off the
        # only connected display (its entries for absent monitors are
        # skipped, its disable entries still apply).  Lid state is ignored
        # here: an explicit switch to a same-monitor profile saved with the
        # lid in the other position is legitimate.
        if not profile_matches_monitor_set(profile, topology):
            raise ValueError(
                f"Profile {name!r} was saved for a different monitor set"
            )
        plan = plan_reconciliation(topology, profile)
        if plan.is_noop:
            await self._applier.mark_profile(name)
            await self._refresh_state()
            return True
        ok = await self._applier.apply_manual(plan.changes, profile_name=name)
        await self._refresh_state()
        return ok

    async def _save_layout(
        self,
        name: str,
        outputs: list[OutputConfig],
        topology_hash: str,
        priority: int,
    ) -> Path:
        if not any(o.enabled for o in outputs):
            # Such a profile would be auto-applied on the next event and turn
            # every display off with no UI left to recover from.
            raise ValueError("Refusing to save a layout with no enabled outputs")
        profile = Profile(
            name=name,
            topology_hash=topology_hash,
            outputs=tuple(outputs),
            priority=priority,
        )
        path = save_profile(profile, self._profile_dir)
        await self._reload_profiles()
        return path

    async def _snapshot_current(self, name: str, priority: int) -> Path:
        topology = await self._backend.get_topology()
        profile = snapshot_to_profile(name, topology, priority=priority)
        path = save_profile(profile, self._profile_dir)
        # The snapshot captures what is on screen right now, so it is by
        # construction the profile in effect.
        await self._applier.mark_profile(name)
        await self._reload_profiles()
        return path

    async def _delete_profile(self, name: str) -> None:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        path = self._profile_dir / f"{safe}.json"
        if path.exists():
            path.unlink()
            log.info("Deleted profile %r (%s)", name, path)
        else:
            log.warning("Profile file for %r not found at %s", name, path)
        # Drop the in-effect record so a later profile reusing this name is
        # not presented as already established on screen.
        await self._applier.clear_profile(name)
        await self._reload_profiles()
