"""Fake backends shared by the worker and controller tests."""

from __future__ import annotations

import threading
import time

from brightd.backends.base import Backlight
from brightd.types import BacklightError, DisplayInfo, DisplayKind


class FakeBacklight(Backlight):
    """Records every write, optionally slowly, optionally failing."""

    def __init__(
        self,
        display_id: str = "test-0",
        *,
        kind: DisplayKind = DisplayKind.INTERNAL,
        delay: float = 0.0,
        min_period: float = 0.0,
        debounce: float = 0.0,
        start: float = 50.0,
        fail: bool = False,
    ) -> None:
        self.min_period = min_period
        self.debounce = debounce
        self._info = DisplayInfo(id=display_id, label=f"Fake {display_id}", kind=kind)
        self._delay = delay
        self._fail = fail
        self._lock = threading.Lock()
        self.writes: list[float] = []
        self.current = start
        self.closed = False

    @property
    def info(self) -> DisplayInfo:
        return self._info

    def read_percent(self) -> float:
        if self._fail:
            raise BacklightError("fake read failure")
        return self.current

    def write_percent(self, percent: float) -> None:
        if self._delay:
            time.sleep(self._delay)
        if self._fail:
            raise BacklightError("fake write failure")
        with self._lock:
            self.writes.append(percent)
            self.current = percent

    def written(self) -> list[float]:
        with self._lock:
            return list(self.writes)

    def close(self) -> None:
        self.closed = True
