"""Serialized display applier with retry, verification, and cooldown."""

from __future__ import annotations

import asyncio
import logging
import shutil

from ..backends.base import DisplayBackend
from ..policy import match_profile, plan_reconciliation
from ..types import OutputConfig, Profile, ReconciliationPlan
from .cooldown import CooldownTracker

log = logging.getLogger(__name__)


async def _notify(summary: str, body: str, urgency: str = "normal") -> None:
    if not shutil.which("notify-send"):
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "notify-send",
            "-u", urgency,
            "-a", "displayd",
            summary,
            body,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
    except OSError:
        pass


def _describe_plan(plan: ReconciliationPlan) -> str:
    parts: list[str] = []
    for connector, cfg in plan.changes:
        if not cfg.enabled:
            parts.append(f"{connector} off")
        else:
            desc = cfg.mode or "auto"
            if cfg.primary:
                desc += ", primary"
            parts.append(f"{connector} {desc}")
    return "\n".join(parts)


class DisplayApplier:
    """Ensures at most one apply operation runs at a time and handles
    retry, post-apply verification, and user-override cooldown."""

    def __init__(
        self,
        backend: DisplayBackend,
        profiles: list[Profile],
        *,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        verify_delay: float = 1.0,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._backend = backend
        self._profiles = profiles
        self._lock = asyncio.Lock()
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._verify_delay = verify_delay
        self._cooldown = CooldownTracker(cooldown_seconds)
        self._last_applied_hash: str = ""

    async def reconcile(self, *, force: bool = False) -> bool:
        """Run a full read-match-apply-verify cycle (serialized)."""
        async with self._lock:
            return await self._reconcile_inner(force)

    async def _reconcile_inner(self, force: bool) -> bool:
        if not force and self._cooldown.is_suppressed:
            log.info("Skipping auto-apply: user-override cooldown active")
            return False

        for attempt in range(1, self._max_retries + 1):
            try:
                topology = await self._backend.get_topology()
            except Exception:
                log.exception(
                    "Topology read failed (attempt %d/%d)",
                    attempt,
                    self._max_retries,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_delay)
                continue

            if not force and topology.full_state_hash == self._last_applied_hash:
                log.debug("Topology unchanged since last apply")
                return True

            profile = match_profile(topology, self._profiles)
            if profile is None:
                log.info("No matching profile; nothing to apply")
                return False

            plan = plan_reconciliation(topology, profile)
            if plan.is_noop:
                self._last_applied_hash = topology.full_state_hash
                return True

            log.info(
                "Applying profile %r (attempt %d/%d, %d change(s))",
                profile.name,
                attempt,
                self._max_retries,
                len(plan.changes),
            )

            try:
                ok = await self._backend.apply(plan.changes)
            except Exception:
                log.exception(
                    "Apply raised (attempt %d/%d)", attempt, self._max_retries
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_delay)
                continue

            if not ok:
                log.warning(
                    "Backend reported failure (attempt %d/%d)",
                    attempt,
                    self._max_retries,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_delay)
                continue

            # Allow the display server a moment to settle before verifying
            await asyncio.sleep(self._verify_delay)

            try:
                verified = await self._backend.verify(plan.changes)
            except Exception:
                log.exception(
                    "Verification raised (attempt %d/%d)",
                    attempt,
                    self._max_retries,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_delay)
                continue

            if verified:
                new_topo = await self._backend.get_topology()
                self._last_applied_hash = new_topo.full_state_hash
                self._cooldown.record_auto_apply()
                log.info("Profile %r applied and verified", profile.name)
                await _notify(
                    f"Display: {profile.name}",
                    _describe_plan(plan),
                )
                return True

            log.warning(
                "Verification mismatch (attempt %d/%d)",
                attempt,
                self._max_retries,
            )
            if attempt < self._max_retries:
                await asyncio.sleep(self._retry_delay)

        log.error("All %d apply attempts exhausted", self._max_retries)
        await _notify(
            "Display: apply failed",
            f"Could not apply profile '{profile.name}' after {self._max_retries} attempts",
            urgency="critical",
        )
        return False

    def reload_profiles(self, profiles: list[Profile]) -> None:
        self._profiles = profiles

    @property
    def cooldown(self) -> CooldownTracker:
        return self._cooldown
