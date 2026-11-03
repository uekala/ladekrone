"""Tests für den Feiertagskalender."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.ladekrone.holidays import (
    easter_sunday,
    holiday_name,
    holidays,
    is_holiday,
    is_special_day,
)


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2019, date(2019, 4, 21)),
        (2024, date(2024, 3, 31)),
        (2025, date(2025, 4, 20)),
        (2026, date(2026, 4, 5)),
        (2027, date(2027, 3, 28)),
        (2038, date(2038, 4, 25)),
    ],
)
def test_easter_sunday(year: int, expected: date) -> None:
    assert easter_sunday(year) == expected


@pytest.mark.parametrize(
    ("state", "count"),
    [
        (None, 9),
        ("NW", 11),  # + Fronleichnam, Allerheiligen
        ("BY", 12),  # + Heilige Drei Könige (Mariä Himmelfahrt nur in Gemeinden)
        ("BB", 12),  # + Ostersonntag, Pfingstsonntag, Reformationstag
        ("SN", 11),  # + Reformationstag, Buß- und Bettag
        ("BE", 10),  # + Frauentag
        ("SL", 12),  # + Fronleichnam, Mariä Himmelfahrt, Allerheiligen
    ],
)
def test_number_of_holidays_2026(state: str | None, count: int) -> None:
    assert len(holidays(2026, state)) == count


def test_state_holidays_2026() -> None:
    assert holiday_name(date(2026, 6, 4), "NW") == "Fronleichnam"
    assert not is_holiday(date(2026, 6, 4), "NI")
    assert not is_holiday(date(2026, 6, 4))  # ohne Bundesland nur bundesweit
    assert is_holiday(date(2026, 11, 1), "NW")
    assert is_holiday(date(2026, 10, 31), "NI")
    assert not is_holiday(date(2026, 10, 31), "NW")
    assert holiday_name(date(2026, 11, 18), "SN") == "Buß- und Bettag"
    assert holiday_name(date(2023, 11, 22), "SN") == "Buß- und Bettag"
    assert is_holiday(date(2026, 1, 6), "BW")
    assert is_holiday(date(2026, 9, 20), "TH")


def test_holidays_with_start_year() -> None:
    assert is_holiday(date(2026, 3, 8), "MV")
    assert not is_holiday(date(2022, 3, 8), "MV")
    assert is_holiday(date(2019, 3, 8), "BE")
    assert not is_holiday(date(2017, 10, 31), "NI")


def test_nationwide_holidays() -> None:
    for day in (
        date(2026, 1, 1),
        date(2026, 4, 3),  # Karfreitag
        date(2026, 4, 6),  # Ostermontag
        date(2026, 5, 1),
        date(2026, 5, 14),  # Christi Himmelfahrt
        date(2026, 5, 25),  # Pfingstmontag
        date(2026, 10, 3),
        date(2026, 12, 25),
        date(2026, 12, 26),
    ):
        assert is_holiday(day), day
    assert not is_holiday(date(2026, 12, 24))
    assert not is_holiday(date(2026, 12, 31))


def test_special_day_kinds() -> None:
    assert is_special_day("publicHoliday", date(2026, 12, 25))
    assert is_special_day("dayBeforePublicHoliday", date(2026, 12, 24))
    assert is_special_day("dayFollowingPublicHoliday", date(2026, 12, 27))
    assert not is_special_day("dayFollowingPublicHoliday", date(2026, 12, 28))
    assert is_special_day("dayBeforePublicHoliday", date(2026, 6, 3), "NW")
    assert not is_special_day("dayBeforePublicHoliday", date(2026, 6, 3), "NI")
    for kind in ("schoolHolidays", "schoolDay", "publicEventDay", "other", None):
        assert not is_special_day(kind, date(2026, 12, 25))
