"""Controller behaviour: caching, listeners, and rescan bookkeeping."""

from __future__ import annotations

from brightd.controller import Controller
from brightd.types import DisplayKind

from .fakes import FakeBacklight


def test_seeds_the_cache_from_hardware() -> None:
    controller = Controller([FakeBacklight(start=30.0)])
    assert controller.percent("test-0") == 30.0
    controller.close()


def test_a_failing_first_read_keeps_the_display() -> None:
    """A transient DDC hiccup must not make the slider row disappear."""
    controller = Controller([FakeBacklight(fail=True)])
    assert [info.id for info in controller.displays] == ["test-0"]
    assert controller.percent("test-0") == 50.0
    controller.close()


def test_set_percent_reaches_the_backend() -> None:
    backlight = FakeBacklight()
    controller = Controller([backlight])
    controller.set_percent("test-0", 80.0)
    assert controller.percent("test-0") == 80.0  # optimistic, before the write lands
    controller.close()
    assert backlight.written()[-1] == 80.0
    assert backlight.closed


def test_set_percent_clamps() -> None:
    controller = Controller([FakeBacklight()])
    controller.set_percent("test-0", 500.0)
    assert controller.percent("test-0") == 100.0
    controller.set_percent("test-0", -20.0)
    assert controller.percent("test-0") == 0.0
    controller.close()


def test_set_percent_for_an_unknown_display_is_a_no_op() -> None:
    controller = Controller([FakeBacklight()])
    controller.set_percent("nope", 10.0)
    controller.close()


def test_nudge_clamps_at_the_ends() -> None:
    controller = Controller([FakeBacklight(start=95.0)])
    assert controller.nudge("test-0", 20.0) == 100.0
    assert controller.nudge("test-0", -500.0) == 0.0
    controller.close()


def test_small_external_changes_are_ignored() -> None:
    """A one-LSB hardware readback must not ping-pong against the slider."""
    seen: list[float] = []

    def record(_display_id: str, percent: float) -> None:
        seen.append(percent)

    controller = Controller([FakeBacklight(start=50.0)])
    controller.add_listener(record)
    controller.note_external_change("test-0", 50.2)
    assert seen == []
    controller.note_external_change("test-0", 70.0)
    assert seen == [70.0]
    assert controller.percent("test-0") == 70.0
    controller.close()


def test_a_broken_listener_does_not_stop_the_others() -> None:
    seen: list[float] = []

    def broken(_display_id: str, _percent: float) -> None:
        raise RuntimeError("boom")

    def record(_display_id: str, percent: float) -> None:
        seen.append(percent)

    controller = Controller([FakeBacklight()])
    controller.add_listener(broken)
    controller.add_listener(record)
    controller.note_external_change("test-0", 90.0)
    assert seen == [90.0]
    controller.close()


def test_primary_prefers_the_internal_panel() -> None:
    external = FakeBacklight("DP-1", kind=DisplayKind.EXTERNAL, start=20.0)
    internal = FakeBacklight("eDP-1", kind=DisplayKind.INTERNAL, start=70.0)
    controller = Controller([external, internal])
    assert controller.primary_percent == 70.0
    controller.close()


def test_rescan_adds_a_new_display_without_disturbing_the_old_one() -> None:
    """Regression: the live backend must not be closed when it reappears."""
    internal = FakeBacklight("eDP-1")
    controller = Controller([internal])
    external = FakeBacklight("DP-1", kind=DisplayKind.EXTERNAL)

    controller.set_backlights([internal, external])

    assert {info.id for info in controller.displays} == {"eDP-1", "DP-1"}
    assert not internal.closed, "the surviving backend must keep its file descriptor"
    controller.close()


def test_rescan_removes_a_departed_display() -> None:
    internal = FakeBacklight("eDP-1")
    external = FakeBacklight("DP-1", kind=DisplayKind.EXTERNAL)
    controller = Controller([internal, external])

    controller.set_backlights([internal])

    assert [info.id for info in controller.displays] == ["eDP-1"]
    assert external.closed
    assert not internal.closed
    controller.close()


def test_refresh_reports_a_value_changed_underneath_us() -> None:
    backlight = FakeBacklight(start=40.0)
    controller = Controller([backlight])
    backlight.current = 85.0  # something else moved the hardware
    assert controller.refresh("test-0") == 85.0
    assert controller.percent("test-0") == 85.0
    controller.close()


def test_refresh_of_a_failing_backend_returns_none() -> None:
    controller = Controller([FakeBacklight(fail=True)])
    assert controller.refresh("test-0") is None
    controller.close()
