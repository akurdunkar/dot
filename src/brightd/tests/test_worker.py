"""The coalescing writer -- the thing that stops a drag flooding the hardware."""

from __future__ import annotations

import time

from brightd.backends.base import Backlight
from brightd.worker import BrightnessWorker, close_all

from .fakes import FakeBacklight


def drain(worker: BrightnessWorker) -> None:
    worker.close(flush=True)
    assert worker.join(5.0), "worker thread did not finish"


def test_a_single_value_is_written() -> None:
    backlight = FakeBacklight()
    worker = BrightnessWorker(backlight)
    worker.submit(42.0)
    drain(worker)
    assert backlight.written() == [42.0]


def test_a_drag_is_coalesced_to_a_few_writes() -> None:
    """100 frame-rate updates against a slow backend must not become 100 writes."""
    backlight = FakeBacklight(delay=0.02)
    worker = BrightnessWorker(backlight)
    for value in range(100):
        worker.submit(float(value))
    drain(worker)

    writes = backlight.written()
    assert writes, "at least one write must land"
    assert len(writes) < 25, f"expected coalescing, got {len(writes)} writes"
    assert writes[-1] == 99.0, "the user's final value must be the one that sticks"


def test_the_last_value_always_wins() -> None:
    backlight = FakeBacklight(delay=0.01)
    worker = BrightnessWorker(backlight)
    for value in (10.0, 20.0, 30.0, 80.0):
        worker.submit(value)
    drain(worker)
    assert backlight.written()[-1] == 80.0


def test_flush_bypasses_the_rate_limit() -> None:
    """A pending value must not sit out a throttle window that shutdown never gives it."""
    backlight = FakeBacklight(min_period=1.0)
    worker = BrightnessWorker(backlight)
    worker.submit(11.0)
    time.sleep(0.05)
    worker.submit(99.0)

    started = time.monotonic()
    drain(worker)
    elapsed = time.monotonic() - started

    assert backlight.written()[-1] == 99.0
    assert elapsed < 0.5, f"flush waited out the rate limit ({elapsed:.2f}s)"


def test_close_without_flush_drops_the_pending_value() -> None:
    backlight = FakeBacklight(min_period=5.0)
    worker = BrightnessWorker(backlight)
    worker.submit(10.0)
    time.sleep(0.05)
    worker.submit(80.0)
    worker.close(flush=False)
    assert worker.join(2.0)
    assert 80.0 not in backlight.written()


def test_submitting_after_close_is_ignored() -> None:
    backlight = FakeBacklight()
    worker = BrightnessWorker(backlight)
    worker.close(flush=False)
    assert worker.join(2.0)
    worker.submit(50.0)
    assert backlight.written() == []


def test_a_backend_error_does_not_kill_the_thread() -> None:
    seen: list[Exception] = []

    def record(_backlight: Backlight, exc: Exception) -> None:
        seen.append(exc)

    backlight = FakeBacklight(fail=True)
    worker = BrightnessWorker(backlight, on_error=record)
    worker.submit(10.0)
    time.sleep(0.1)
    worker.submit(20.0)
    drain(worker)
    assert len(seen) >= 1


def test_debounce_collapses_a_quick_flick() -> None:
    backlight = FakeBacklight(debounce=0.15)
    worker = BrightnessWorker(backlight)
    worker.submit(30.0)
    worker.submit(60.0)
    worker.submit(90.0)
    drain(worker)
    assert backlight.written() == [90.0], "a flick should cost exactly one write"


def test_close_all_shuts_down_every_worker() -> None:
    backlights = [FakeBacklight(f"d{index}") for index in range(3)]
    workers = [BrightnessWorker(backlight) for backlight in backlights]
    for worker, value in zip(workers, (10.0, 20.0, 30.0)):
        worker.submit(value)
    close_all(workers, timeout=5.0)
    assert [backlight.written()[-1] for backlight in backlights] == [10.0, 20.0, 30.0]
