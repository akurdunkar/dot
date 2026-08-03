"""The month grid, which is the whole of what the panel shows.

The panel builds its widgets once and only relabels them, so every invariant it
relies on -- six rows, seven columns, a contiguous run of dates -- is a
correctness property here rather than something the UI can defend itself
against.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

import pytest

from calendard.month import (
    COLUMNS,
    MAX_YEAR,
    MIN_YEAR,
    ROWS,
    WeekStart,
    build_month,
    shift_month,
    shift_year,
    weekday_labels,
)

WEEK_STARTS = [WeekStart.MONDAY, WeekStart.SUNDAY]

# A short month that needs padding, a leap February, two year boundaries and an
# ordinary month.
SAMPLE_MONTHS = [(2021, 2), (2024, 2), (2025, 12), (2026, 1), (2026, 8)]


def cells(year: int, month: int, week_start: WeekStart) -> list[date]:
    view = build_month(year, month, week_start)
    return [cell.date for week in view.weeks for cell in week.days]


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


class TestShape:
    @pytest.mark.parametrize("week_start", WEEK_STARTS)
    @pytest.mark.parametrize(("year", "month"), SAMPLE_MONTHS)
    def test_always_six_rows_of_seven(self, year: int, month: int, week_start: WeekStart) -> None:
        """February 2021 fits in four rows and August 2026 needs six.

        Both must produce six: the panel is an override-redirect window sized
        from its own content, so a grid whose height followed the month would
        move the window under the pointer as you page.
        """
        view = build_month(year, month, week_start)
        assert len(view.weeks) == ROWS
        assert all(len(week.days) == COLUMNS for week in view.weeks)

    @pytest.mark.parametrize("week_start", WEEK_STARTS)
    @pytest.mark.parametrize(("year", "month"), SAMPLE_MONTHS)
    def test_dates_are_contiguous(self, year: int, month: int, week_start: WeekStart) -> None:
        days = cells(year, month, week_start)
        assert days == [days[0] + timedelta(days=offset) for offset in range(ROWS * COLUMNS)]

    @pytest.mark.parametrize("week_start", WEEK_STARTS)
    @pytest.mark.parametrize(("year", "month"), SAMPLE_MONTHS)
    def test_every_row_starts_on_the_week_start(
        self, year: int, month: int, week_start: WeekStart
    ) -> None:
        view = build_month(year, month, week_start)
        assert all(week.days[0].date.weekday() == int(week_start) for week in view.weeks)

    def test_padding_extends_forward(self) -> None:
        """February 2021 starts exactly on a Monday and needs two extra rows.

        They are appended, not prepended: prepending would push every date of
        the month two rows down relative to a month that did not need padding.
        """
        view = build_month(2021, 2, WeekStart.MONDAY)
        assert view.weeks[0].days[0].date == date(2021, 2, 1)
        assert view.weeks[-1].days[-1].date == date(2021, 3, 14)


# ---------------------------------------------------------------------------
# in_month
# ---------------------------------------------------------------------------


class TestInMonth:
    @pytest.mark.parametrize("week_start", WEEK_STARTS)
    @pytest.mark.parametrize(("year", "month"), SAMPLE_MONTHS)
    def test_flags_exactly_the_month(
        self, year: int, month: int, week_start: WeekStart
    ) -> None:
        view = build_month(year, month, week_start)
        inside = [cell.date for week in view.weeks for cell in week.days if cell.in_month]
        length = calendar.monthrange(year, month)[1]
        assert inside == [date(year, month, day) for day in range(1, length + 1)]

    def test_leap_february_has_twenty_nine(self) -> None:
        view = build_month(2024, 2, WeekStart.MONDAY)
        assert sum(cell.in_month for week in view.weeks for cell in week.days) == 29

    def test_padding_rows_are_outside(self) -> None:
        """The rows appended to a short month are all filler."""
        view = build_month(2021, 2, WeekStart.MONDAY)
        assert not any(cell.in_month for cell in view.weeks[-1].days)

    def test_same_day_number_in_a_neighbouring_year_is_not_in_month(self) -> None:
        """January's leading days are the previous *year* -- the month number
        alone would mark 2025-12-29 as inside January."""
        view = build_month(2026, 1, WeekStart.MONDAY)
        first = view.weeks[0].days[0]
        assert first.date == date(2025, 12, 29)
        assert not first.in_month


# ---------------------------------------------------------------------------
# Labels and titles
# ---------------------------------------------------------------------------


class TestLabels:
    def test_monday_start(self) -> None:
        assert weekday_labels(WeekStart.MONDAY) == ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")

    def test_sunday_start(self) -> None:
        assert weekday_labels(WeekStart.SUNDAY) == ("Su", "Mo", "Tu", "We", "Th", "Fr", "Sa")

    @pytest.mark.parametrize("week_start", WEEK_STARTS)
    def test_labels_line_up_with_the_columns(self, week_start: WeekStart) -> None:
        """The header is generated separately from the grid, so they can drift."""
        view = build_month(2026, 8, week_start)
        names = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
        for column, label in enumerate(view.weekday_labels):
            assert label == names[view.weeks[0].days[column].date.weekday()]

    def test_title(self) -> None:
        assert build_month(2026, 8, WeekStart.MONDAY).title == "August 2026"


# ---------------------------------------------------------------------------
# ISO week numbers
# ---------------------------------------------------------------------------


class TestIsoWeek:
    def test_ordinary_month(self) -> None:
        view = build_month(2026, 8, WeekStart.MONDAY)
        assert [week.iso_week for week in view.weeks] == [31, 32, 33, 34, 35, 36]

    @pytest.mark.parametrize("week_start", WEEK_STARTS)
    def test_turn_of_year(self, week_start: WeekStart) -> None:
        """January 2026's first row starts in December either way.

        Numbering from the row's first day would call it week 52 of 2025; ISO
        numbers a week by its Thursday, which is already in 2026.
        """
        view = build_month(2026, 1, week_start)
        assert [week.iso_week for week in view.weeks] == [1, 2, 3, 4, 5, 6]

    def test_padded_rows_keep_counting(self) -> None:
        view = build_month(2021, 2, WeekStart.MONDAY)
        assert [week.iso_week for week in view.weeks] == [5, 6, 7, 8, 9, 10]


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


class TestShift:
    def test_zero_is_identity(self) -> None:
        assert shift_month(2026, 8, 0) == (2026, 8)

    def test_forward_within_a_year(self) -> None:
        assert shift_month(2026, 8, 3) == (2026, 11)

    def test_forward_across_the_year_boundary(self) -> None:
        assert shift_month(2026, 12, 1) == (2027, 1)

    def test_backward_across_the_year_boundary(self) -> None:
        assert shift_month(2026, 1, -1) == (2025, 12)

    def test_multi_year_jump(self) -> None:
        assert shift_month(2026, 8, 30) == (2029, 2)
        assert shift_month(2026, 8, -30) == (2024, 2)

    def test_year_shift_keeps_the_month(self) -> None:
        assert shift_year(2026, 2, 1) == (2027, 2)
        assert shift_year(2024, 2, -4) == (2020, 2)

    def test_clamps_rather_than_wrapping(self) -> None:
        """This backs the arrow keys: held down at the end of the range it
        should stop, not roll over to the other end."""
        assert shift_month(MAX_YEAR, 12, 1) == (MAX_YEAR, 12)
        assert shift_month(MIN_YEAR, 1, -1) == (MIN_YEAR, 1)
        assert shift_month(2026, 8, 10**6) == (MAX_YEAR, 12)
        assert shift_month(2026, 8, -(10**6)) == (MIN_YEAR, 1)

    @pytest.mark.parametrize("week_start", WEEK_STARTS)
    def test_the_clamped_ends_are_buildable(self, week_start: WeekStart) -> None:
        """The range exists so navigation cannot walk into a month whose
        padding would run off date.min/date.max."""
        for year, month in (shift_month(2026, 8, 10**6), shift_month(2026, 8, -(10**6))):
            assert len(build_month(year, month, week_start).weeks) == ROWS


class TestValidation:
    @pytest.mark.parametrize("month", [0, 13, -1, 100])
    def test_rejects_bad_month(self, month: int) -> None:
        with pytest.raises(ValueError):
            build_month(2026, month)

    @pytest.mark.parametrize("year", [MIN_YEAR - 1, MAX_YEAR + 1, 0])
    def test_rejects_out_of_range_year(self, year: int) -> None:
        with pytest.raises(ValueError):
            build_month(year, 1)
