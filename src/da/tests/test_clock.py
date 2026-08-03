"""Day-rollover timing.

The process runs for weeks, so the only thing standing between it and a stale
date on screen is this delay calculation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from da.clock import MAX_DELAY_SECONDS, seconds_until_midnight


class TestSecondsUntilMidnight:
    def test_just_before_midnight(self) -> None:
        assert seconds_until_midnight(datetime(2026, 8, 3, 23, 59, 30)) == 30.0

    def test_exactly_at_midnight_waits_a_full_day_capped(self) -> None:
        assert seconds_until_midnight(datetime(2026, 8, 3, 0, 0, 0)) == MAX_DELAY_SECONDS

    def test_sub_second_precision_is_kept(self) -> None:
        now = datetime(2026, 8, 3, 23, 59, 56, 750_000)
        assert seconds_until_midnight(now) == pytest.approx(3.25)

    def test_floors_at_one_second(self) -> None:
        """A non-positive delay would spin the main loop, so the last fraction
        of a second before midnight is rounded up to a whole one -- which lands
        just after the rollover rather than just before it."""
        assert seconds_until_midnight(datetime(2026, 8, 3, 23, 59, 59, 500_000)) == 1.0
        assert seconds_until_midnight(datetime(2026, 8, 3, 23, 59, 59, 999_999)) == 1.0

    @pytest.mark.parametrize("hour", range(24))
    def test_capped_so_a_clock_jump_cannot_hide_a_rollover(self, hour: int) -> None:
        """GLib timers are monotonic, so a suspend across midnight or an NTP
        step fires them at the wrong moment; the cap bounds how long a stale
        date can stay on screen."""
        delay = seconds_until_midnight(datetime(2026, 8, 3, hour, 30))
        assert 0 < delay <= MAX_DELAY_SECONDS

    def test_uncapped_delay_lands_exactly_on_midnight(self) -> None:
        now = datetime(2026, 8, 3, 14, 22, 7)
        delay = seconds_until_midnight(now, max_delay=86_400.0)
        assert now + timedelta(seconds=delay) == datetime(2026, 8, 4, 0, 0, 0)

    def test_month_and_year_boundaries(self) -> None:
        for now, expected in (
            (datetime(2026, 8, 31, 23, 59, 0), datetime(2026, 9, 1)),
            (datetime(2026, 12, 31, 23, 59, 0), datetime(2027, 1, 1)),
            (datetime(2024, 2, 28, 23, 59, 0), datetime(2024, 2, 29)),
        ):
            delay = seconds_until_midnight(now, max_delay=86_400.0)
            assert now + timedelta(seconds=delay) == expected

    def test_aware_datetimes_do_not_raise(self) -> None:
        """``datetime.combine`` drops the tzinfo unless it is passed through,
        and subtracting a naive from an aware datetime is a TypeError."""
        now = datetime(2026, 8, 3, 23, 59, 30, tzinfo=timezone.utc)
        assert seconds_until_midnight(now) == 30.0
