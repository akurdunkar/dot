"""Day rollover.

A tray calendar that shows the wrong day is worse than no tray calendar, and
this process can easily be running for weeks, so "today" has to be re-derived
rather than captured at startup.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Callable

from gi.repository import GLib

log = logging.getLogger(__name__)

MAX_DELAY_SECONDS = 3600.0
"""Longest a single timer may sleep.

GLib timeouts run on the monotonic clock, so anything that moves the wall clock
underneath us -- suspend/resume across midnight, an NTP step, a timezone change
-- fires the timer at the wrong moment or not at all.  Re-checking at least
hourly bounds how long a stale date can be displayed, and costs 24 wakeups a
day that do nothing but compare two dates.
"""


def seconds_until_midnight(
    now: datetime,
    *,
    max_delay: float = MAX_DELAY_SECONDS,
) -> float:
    """Seconds from ``now`` to the next local midnight, capped at ``max_delay``.

    Accepts naive or aware datetimes; the result is a wall-clock delta, which a
    DST transition can make wrong by an hour.  That is deliberate rather than
    corrected: the cap re-checks often enough to absorb it, and threading a
    timezone database through here to shave an hour off a once-a-year edge case
    would buy nothing a user could notice.
    """
    midnight = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=now.tzinfo)
    delay = (midnight - now).total_seconds()
    # Floor at 1s: a zero or negative delay (clock stepped forward past
    # midnight between the two reads) would spin the main loop.
    return max(1.0, min(delay, max_delay))


class DayWatcher:
    """Calls ``on_new_day`` on the GTK main loop when the local date changes."""

    def __init__(self, on_new_day: Callable[[date], None]) -> None:
        self._on_new_day = on_new_day
        self._today = date.today()
        self._source_id: int | None = None

    @property
    def today(self) -> date:
        return self._today

    def start(self) -> None:
        if self._source_id is None:
            self._arm()

    def stop(self) -> None:
        if self._source_id is not None:
            GLib.source_remove(self._source_id)
            self._source_id = None

    def _arm(self) -> None:
        delay = seconds_until_midnight(datetime.now())
        # Milliseconds rather than timeout_add_seconds: the second-granularity
        # variant is free to coalesce by up to a second, which would fire just
        # *before* midnight and read the old date.
        self._source_id = GLib.timeout_add(int(delay * 1000.0) + 100, self._on_tick)

    def _on_tick(self) -> bool:
        self._source_id = None
        try:
            today = date.today()
            if today != self._today:
                log.info("Date rolled over to %s", today.isoformat())
                self._today = today
                self._on_new_day(today)
        except Exception:  # noqa: BLE001 -- PyGObject swallows this, and a
            # dead timer would freeze the date until the next restart.
            log.exception("Day rollover handler failed")
        self._arm()
        # The next timer is armed explicitly rather than by returning
        # SOURCE_CONTINUE: the delay has to be recomputed from the new time.
        return GLib.SOURCE_REMOVE
