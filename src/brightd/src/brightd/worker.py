"""Serialised, coalescing brightness writes.

A slider drag emits ``value-changed`` at the frame-clock rate -- about 60 Hz.
That is harmless for a 70 us sysfs write and catastrophic for a 300 ms DDC
write, where it would both freeze the UI and flood the monitor's I2C engine.

So every backend gets one worker thread holding a single *slot* rather than a
queue: a newer value overwrites an unsent older one, and a drag from 10% to 80%
becomes a handful of writes instead of hundreds.  The throttle numbers come
from the backend itself (:attr:`Backlight.debounce`, :attr:`Backlight.min_period`),
so the same worker drives an unthrottled sysfs panel and a heavily rate-limited
DDC monitor without knowing the difference.

Writes happen outside the lock, so a slow write never blocks the GTK thread
submitting newer values.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .backends.base import Backlight

log = logging.getLogger(__name__)

ErrorHandler = Callable[[Backlight, Exception], None]
Clock = Callable[[], float]


class BrightnessWorker:
    """Owns all writes to one backend."""

    def __init__(
        self,
        backlight: Backlight,
        *,
        on_error: ErrorHandler | None = None,
        clock: Clock = time.monotonic,
    ) -> None:
        self._backlight = backlight
        self._on_error = on_error
        self._clock = clock

        self._cv = threading.Condition()
        self._pending: float | None = None
        self._not_before: float = 0.0
        self._last_write_at: float | None = None
        self._closing = False
        self._flushing = False

        self._thread = threading.Thread(
            target=self._run,
            name=f"brightd-write-{backlight.info.id}",
            daemon=True,
        )
        self._thread.start()

    @property
    def backlight(self) -> Backlight:
        return self._backlight

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------

    def submit(self, percent: float) -> None:
        """Request ``percent``, superseding any value not yet written."""
        with self._cv:
            if self._closing:
                return
            if self._pending is None:
                self._not_before = self._earliest_write_time()
            self._pending = percent
            self._cv.notify()

    def _earliest_write_time(self) -> float:
        """When the next write may go out.  Caller holds the lock.

        A gesture that starts from idle waits out ``debounce`` so a quick flick
        costs one write rather than two; a gesture already in flight is instead
        paced by ``min_period``.
        """
        now = self._clock()
        min_period = self._backlight.min_period
        if self._last_write_at is None or (now - self._last_write_at) >= min_period:
            return now + self._backlight.debounce
        return self._last_write_at + min_period

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while True:
            value = self._claim()
            if value is None:
                return
            try:
                self._backlight.write_percent(value)
            except Exception as exc:  # noqa: BLE001 -- a backend must not kill the thread
                log.error("Write to %s failed: %s", self._backlight.info.id, exc)
                if self._on_error is not None:
                    self._on_error(self._backlight, exc)

    def _claim(self) -> float | None:
        """Block until a value is due, then take it.  ``None`` means stop."""
        with self._cv:
            while True:
                if self._pending is None:
                    if self._closing:
                        return None
                    self._cv.wait()
                    continue
                # A flush must bypass the throttle: the user's last slider
                # value would otherwise sit in the slot waiting out a window
                # that shutdown never gives it.
                delay = 0.0 if self._flushing else self._not_before - self._clock()
                if delay > 0:
                    self._cv.wait(delay)
                    continue
                value = self._pending
                self._pending = None
                self._last_write_at = self._clock()
                return value

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def close(self, *, flush: bool = True) -> None:
        """Stop accepting work.  With ``flush``, the pending value still goes out."""
        with self._cv:
            self._closing = True
            self._flushing = flush
            if not flush:
                self._pending = None
            self._cv.notify_all()

    def join(self, timeout: float) -> bool:
        """Wait for the thread to finish.  ``False`` if it is still running."""
        self._thread.join(timeout)
        return not self._thread.is_alive()


def close_all(workers: list[BrightnessWorker], *, timeout: float = 2.0) -> None:
    """Shut down every worker against one shared deadline.

    Closing them serially would make N monitors cost N timeouts.  Threads are
    daemons, so a worker still stuck in a wedged ddcutil call is abandoned with
    a warning rather than hanging shutdown.
    """
    for worker in workers:
        worker.close(flush=True)
    deadline = time.monotonic() + timeout
    for worker in workers:
        remaining = max(0.0, deadline - time.monotonic())
        if not worker.join(remaining):
            log.warning(
                "Write worker for %s did not finish within %.1fs; abandoning",
                worker.backlight.info.id,
                timeout,
            )
