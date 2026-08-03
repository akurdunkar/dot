"""Month-grid construction.

Pure: no GTK, no clock, no globals.  Everything that decides *what* the panel
shows lives here so it can be tested without an X server, which leaves the UI
modules holding only placement and drawing.

The grid is always six rows.  A real month needs four to six depending on its
length and start weekday, and letting the row count follow the month would make
the panel change height as you page through the year -- it is an
override-redirect window positioned from its own size, so it would resize and
jump under the pointer somewhere between February and August.  Six rows always
means every month lands on the same pixels, and paging reads as the dates
changing rather than the window redrawing.  It also means the widget grid can
be built once and only ever have its text rewritten, which matters because
rebuilding widgets while the panel holds a seat grab would destroy the very
widgets holding it.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from enum import IntEnum
from typing import Sequence

ROWS = 6
"""Week rows in the grid, always -- see the module docstring."""

COLUMNS = 7

MIN_YEAR = 1900
MAX_YEAR = 2999
"""Navigable range.

The stdlib grid builder pads into the adjacent months, so the true limit sits a
few days inside ``date.min``/``date.max`` and differs by week start -- a
Sunday-start January of year 1 would need year 0.  Rather than encode that
corner, navigation is clamped to a range that comfortably contains any date a
tray calendar is useful for.
"""

_WEEKDAY_LABELS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
"""Indexed by ``date.weekday()``, so Monday is 0."""

_THURSDAY = 3


class WeekStart(IntEnum):
    """Leftmost column of the grid, numbered as ``date.weekday()``.

    The values are what ``calendar.Calendar`` wants for ``firstweekday``, so
    they can be passed straight through.
    """

    MONDAY = 0
    SUNDAY = 6


@dataclass(frozen=True, slots=True)
class Cell:
    """One day box.

    ``in_month`` is false for the leading and trailing days borrowed from the
    neighbouring months.  They are shown rather than blanked so the grid reads
    as a continuous strip of dates -- which is the whole point of a calendar
    you only navigate.
    """

    date: date
    in_month: bool


@dataclass(frozen=True, slots=True)
class Week:
    days: tuple[Cell, ...]
    iso_week: int


@dataclass(frozen=True, slots=True)
class MonthView:
    """Everything the panel needs to draw one month."""

    year: int
    month: int
    week_start: WeekStart
    weeks: tuple[Week, ...]
    weekday_labels: tuple[str, ...]

    @property
    def title(self) -> str:
        return f"{calendar.month_name[self.month]} {self.year}"


def weekday_labels(week_start: WeekStart) -> tuple[str, ...]:
    """Column headers, rotated so ``week_start`` comes first."""
    start = int(week_start)
    return tuple(_WEEKDAY_LABELS[(start + offset) % COLUMNS] for offset in range(COLUMNS))


def _iso_week(row: Sequence[date]) -> int:
    """ISO week number for a grid row.

    ISO 8601 numbers a week by the year its Thursday falls in, so the Thursday
    is the only unambiguous day to read it from: on a Sunday-start grid the row
    straddles two ISO weeks, and taking the first or last day would label the
    turn-of-year rows off by one.  Every 7-day row contains exactly one
    Thursday whichever day it starts on.
    """
    for day in row:
        if day.weekday() == _THURSDAY:
            return day.isocalendar().week
    raise ValueError(f"row of {len(row)} days contains no Thursday")


def build_month(
    year: int,
    month: int,
    week_start: WeekStart = WeekStart.MONDAY,
) -> MonthView:
    """Build the six-row grid for ``month`` of ``year``."""
    if not 1 <= month <= 12:
        raise ValueError(f"month out of range: {month}")
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise ValueError(f"year out of range [{MIN_YEAR}, {MAX_YEAR}]: {year}")

    rows: list[list[date]] = calendar.Calendar(firstweekday=int(week_start)).monthdatescalendar(
        year, month
    )
    # Pad short months forward rather than backward: the month's own days keep
    # the row they would naturally have, so paging never shifts a date sideways.
    while len(rows) < ROWS:
        last = rows[-1][-1]
        rows.append([last + timedelta(days=offset) for offset in range(1, COLUMNS + 1)])

    weeks = tuple(
        Week(
            days=tuple(
                Cell(date=day, in_month=day.month == month and day.year == year) for day in row
            ),
            iso_week=_iso_week(row),
        )
        for row in rows[:ROWS]
    )
    return MonthView(
        year=year,
        month=month,
        week_start=week_start,
        weeks=weeks,
        weekday_labels=weekday_labels(week_start),
    )


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """Move ``delta`` months, clamped to the navigable range.

    Clamping rather than wrapping or raising: this backs the arrow keys, and
    holding one down at the end of the range should stop, not roll over to 1900.
    """
    index = year * 12 + (month - 1) + delta
    index = max(MIN_YEAR * 12, min(index, MAX_YEAR * 12 + 11))
    shifted_year, month_index = divmod(index, 12)
    return shifted_year, month_index + 1


def shift_year(year: int, month: int, delta: int) -> tuple[int, int]:
    """Move ``delta`` years, keeping the month."""
    return shift_month(year, month, delta * 12)
