"""User-override suppression: prevent auto-apply from immediately reverting
a manual display change the user just made."""

from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)


class CooldownTracker:
    """Tracks a cooldown window after the user manually adjusts displays.

    While the cooldown is active, automatic profile application is suppressed
    so the user's intent is respected.
    """

    def __init__(self, cooldown_seconds: float = 30.0) -> None:
        self._cooldown = cooldown_seconds
        self._last_manual: float = 0.0

    def record_manual_change(self) -> None:
        self._last_manual = time.monotonic()
        log.info(
            "Manual display change recorded; cooldown active for %.0f s",
            self._cooldown,
        )

    def record_auto_apply(self) -> None:
        """Called after a successful automatic apply (informational)."""

    @property
    def is_suppressed(self) -> bool:
        if self._last_manual <= 0:
            return False
        remaining = self._cooldown - (time.monotonic() - self._last_manual)
        if remaining > 0:
            log.debug("Auto-apply suppressed: %.1f s remaining", remaining)
            return True
        return False

    def reset(self) -> None:
        self._last_manual = 0.0
