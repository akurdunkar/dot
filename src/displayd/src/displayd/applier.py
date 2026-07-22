"""Serialized display applier with retry, verification, and cooldown."""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Optional

from .backends.base import DisplayBackend
from .cooldown import CooldownTracker
from .policy import match_profile, plan_reconciliation
from .types import OutputConfig, Profile, ReconciliationPlan

log = logging.getLogger(__name__)


async def _notify(summary: str, body: str, urgency: str = "normal") -> None:
    if not shutil.which("notify-send"):
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "notify-send",
            "-u",
            urgency,
            "-a",
            "displayd",
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
        #: Name of the profile most recently established on screen (by a
        #: reconcile or a profile-driven manual apply); None when the current
        #: layout is not known to correspond to any profile. Only touched on
        #: the engine loop thread.
        self.last_profile: Optional[str] = None

    async def reconcile(self, *, force: bool = False) -> bool:
        """Run a full read-match-apply-verify cycle (serialized)."""
        async with self._lock:
            return await self._reconcile_inner(force)

    async def _reconcile_inner(self, force: bool) -> bool:
        if not force and self._cooldown.is_suppressed:
            log.info("Skipping auto-apply: user-override cooldown active")
            return False

        profile: Profile | None = None
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
                self.last_profile = None
                return False

            plan = plan_reconciliation(topology, profile)
            if plan.is_noop:
                self._last_applied_hash = topology.full_state_hash
                self.last_profile = profile.name
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
                self.last_profile = profile.name
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
        name = profile.name if profile is not None else "(unknown)"
        await _notify(
            "Display: apply failed",
            f"Could not apply profile '{name}' after {self._max_retries} attempts",
            urgency="critical",
        )
        return False

    async def apply_manual(
        self,
        changes: list[tuple[str, OutputConfig]],
        profile_name: Optional[str] = None,
    ) -> bool:
        """Apply a user-supplied layout (serialized), bypassing profile matching.

        Always records a manual change so auto-apply backs off, even when the
        apply itself fails. When the layout corresponds to a saved profile,
        pass its name via profile_name so it is recorded as the profile in
        effect; ad-hoc layouts (profile_name=None) clear that record.
        """
        async with self._lock:
            try:
                ok = False
                try:
                    ok = await self._backend.apply(changes)
                except Exception:
                    log.exception("Manual apply raised")

                if not ok:
                    log.warning("Manual apply failed")
                    await _notify(
                        "Display: manual apply failed",
                        f"Backend rejected {len(changes)} change(s)",
                        urgency="critical",
                    )
                    return False

                await asyncio.sleep(self._verify_delay)

                try:
                    verified = await self._backend.verify(changes)
                except Exception:
                    log.exception("Manual apply verification raised")
                    verified = False

                if not verified:
                    log.warning("Manual apply verification mismatch")
                    self.last_profile = None
                    await _notify(
                        "Display: manual apply failed",
                        "Applied layout did not verify",
                        urgency="critical",
                    )
                    return False

                new_topo = await self._backend.get_topology()
                self._last_applied_hash = new_topo.full_state_hash
                self.last_profile = profile_name
                log.info("Manual layout applied and verified")
                await _notify(
                    "Display: manual layout applied",
                    f"{len(changes)} change(s)",
                )
                return True
            finally:
                self._cooldown.record_manual_change()

    async def mark_profile(self, profile_name: Optional[str]) -> None:
        """Record profile_name as the profile in effect without applying.

        Serialized behind the apply lock so an in-flight reconcile or manual
        apply cannot overwrite the record afterwards.
        """
        async with self._lock:
            self.last_profile = profile_name

    async def clear_profile(self, profile_name: str) -> None:
        """Forget the in-effect record if it names the given profile."""
        async with self._lock:
            if self.last_profile == profile_name:
                self.last_profile = None

    def reload_profiles(self, profiles: list[Profile]) -> None:
        self._profiles = profiles

    @property
    def cooldown(self) -> CooldownTracker:
        return self._cooldown
