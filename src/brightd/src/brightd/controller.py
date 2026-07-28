"""Display registry and brightness state, with no GTK dependency.

The UI never touches a backend directly.  It asks the controller for the list
of displays and their current percentages, and pushes new values in; the
controller keeps an *optimistic* cache so the slider tracks the finger at frame
rate while the actual write is still in flight behind the worker.

Keeping this module free of GTK is what lets ``brightd-ctl`` reuse it, and what
makes the whole thing testable against fake backends.
"""

from __future__ import annotations

import logging
from typing import Callable, Sequence

from .backends.base import Backlight
from .backends.sysfs import SysfsBacklight
from .curve import clamp
from .types import BacklightError, DisplayInfo, DisplayKind
from .worker import BrightnessWorker, close_all

log = logging.getLogger(__name__)

Listener = Callable[[str, float], None]
"""Called with ``(display_id, percent)`` when a value changes underneath us."""


class Controller:
    """Owns every controllable display and the workers that write to them."""

    def __init__(self, backlights: Sequence[Backlight]) -> None:
        self._backlights: dict[str, Backlight] = {}
        self._workers: dict[str, BrightnessWorker] = {}
        self._percent: dict[str, float] = {}
        self._listeners: list[Listener] = []
        for backlight in backlights:
            self._adopt(backlight)

    def _adopt(self, backlight: Backlight) -> None:
        """Start a worker for ``backlight`` and seed its cached value."""
        display_id = backlight.info.id
        self._backlights[display_id] = backlight
        self._workers[display_id] = BrightnessWorker(backlight, on_error=self._on_write_error)
        try:
            self._percent[display_id] = backlight.read_percent()
        except BacklightError as exc:
            # A monitor that fails its first read is kept in the list with a
            # neutral value: dropping it would make the row vanish for what is
            # usually a transient DDC hiccup.
            log.warning("Initial read of %s failed: %s", display_id, exc)
            self._percent[display_id] = 50.0

    def set_backlights(self, backlights: Sequence[Backlight]) -> None:
        """Replace the display set after a rescan.

        Displays that are still present keep their existing worker and cached
        value, so a rescan never interrupts an in-flight write or makes a
        slider jump.
        """
        incoming = {backlight.info.id: backlight for backlight in backlights}

        for display_id in [d for d in self._backlights if d not in incoming]:
            worker = self._workers.pop(display_id, None)
            if worker is not None:
                worker.close(flush=False)  # the display is gone; nothing to flush to
            self._backlights.pop(display_id).close()
            self._percent.pop(display_id, None)
            log.info("Display %s disappeared", display_id)

        for display_id, backlight in incoming.items():
            existing = self._backlights.get(display_id)
            if existing is not None:
                # Keep the live backend. Only close a genuinely new duplicate --
                # closing ``existing`` itself would shut the fd we are still using.
                if backlight is not existing:
                    backlight.close()
                continue
            log.info("Display %s appeared", display_id)
            self._adopt(backlight)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def displays(self) -> list[DisplayInfo]:
        return [backlight.info for backlight in self._backlights.values()]

    @property
    def internal(self) -> Backlight | None:
        """The built-in panel, if there is one.

        This is the display the scroll wheel and the keyboard bindings act on.
        """
        for backlight in self._backlights.values():
            if backlight.info.kind is DisplayKind.INTERNAL:
                return backlight
        return None

    @property
    def sysfs_backlight(self) -> SysfsBacklight | None:
        """The kernel backlight specifically, if any.

        Distinct from :attr:`internal` because only a kernel backlight offers
        the ``POLLPRI`` change notification the watcher needs -- identifying it
        by *kind* would hand the watcher a DDC monitor it cannot poll.
        """
        for backlight in self._backlights.values():
            if isinstance(backlight, SysfsBacklight):
                return backlight
        return None

    def percent(self, display_id: str) -> float:
        return self._percent.get(display_id, 0.0)

    @property
    def primary_percent(self) -> float:
        """Level the tray icon reflects: the internal panel, else the first display."""
        internal = self.internal
        if internal is not None:
            return self.percent(internal.info.id)
        return next(iter(self._percent.values()), 0.0)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def set_percent(self, display_id: str, percent: float) -> None:
        """Request a new level, updating the cache immediately."""
        worker = self._workers.get(display_id)
        if worker is None:
            return
        value = clamp(percent, 0.0, 100.0)
        self._percent[display_id] = value
        worker.submit(value)

    def nudge(self, display_id: str, delta: float) -> float:
        """Adjust by ``delta`` percentage points.  Returns the new value."""
        value = clamp(self.percent(display_id) + delta, 0.0, 100.0)
        self.set_percent(display_id, value)
        return value

    def refresh(self, display_id: str) -> float | None:
        """Re-read hardware and notify listeners if it moved.

        Returns the new percentage, or ``None`` if the display is gone or the
        read failed.
        """
        backlight = self._backlights.get(display_id)
        if backlight is None:
            return None
        try:
            value = backlight.read_percent()
        except BacklightError as exc:
            log.warning("Refresh of %s failed: %s", display_id, exc)
            return None
        self.note_external_change(display_id, value)
        return value

    def note_external_change(self, display_id: str, percent: float) -> None:
        """Record a change that came from outside brightd and tell listeners.

        Small movements are ignored so a one-LSB hardware readback quantisation
        cannot ping-pong against the slider.
        """
        previous = self._percent.get(display_id)
        if previous is not None and abs(previous - percent) < 0.5:
            return
        self._percent[display_id] = percent
        self._notify(display_id, percent)

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def _notify(self, display_id: str, percent: float) -> None:
        for listener in self._listeners:
            try:
                listener(display_id, percent)
            except Exception:  # noqa: BLE001 -- one bad listener must not stop the rest
                log.exception("Brightness listener failed")

    def _on_write_error(self, backlight: Backlight, exc: Exception) -> None:
        log.error("Backend %s write error: %s", backlight.info.id, exc)

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def close(self, *, timeout: float = 2.0) -> None:
        """Flush pending writes, then release every backend."""
        close_all(list(self._workers.values()), timeout=timeout)
        for backlight in self._backlights.values():
            backlight.close()
