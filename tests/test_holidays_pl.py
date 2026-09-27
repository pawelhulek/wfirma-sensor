"""Polish public holidays and the Tax Ordinance's next-business-day rule."""

from datetime import date

import pytest

from custom_components.wfirma.holidays_pl import easter_sunday, is_day_off, next_business_day, public_holidays


@pytest.mark.parametrize(
    ("year", "expected"),
    [(2025, date(2025, 4, 20)), (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28)), (2038, date(2038, 4, 25))],
)
def test_easter_sunday(year: int, expected: date) -> None:
    assert easter_sunday(year) == expected


def test_2026_holidays() -> None:
    days = public_holidays(2026)
    assert date(2026, 4, 6) in days  # Easter Monday
    assert date(2026, 6, 4) in days  # Corpus Christi, Easter + 60
    assert date(2026, 5, 24) in days  # Pentecost
    assert date(2026, 12, 24) in days  # Christmas Eve, a holiday since 2025
    assert date(2026, 11, 11) in days
    assert date(2026, 11, 12) not in days


def test_christmas_eve_was_a_working_day_before_2025() -> None:
    assert date(2024, 12, 24) not in public_holidays(2024)


@pytest.mark.parametrize(
    ("day", "off"),
    [(date(2026, 9, 19), True), (date(2026, 9, 20), True), (date(2026, 9, 21), False), (date(2026, 1, 6), True)],
    ids=["saturday", "sunday", "monday", "epiphany"],
)
def test_is_day_off(day: date, off: bool) -> None:
    assert is_day_off(day) is off


@pytest.mark.parametrize(
    ("due", "expected"),
    [
        (date(2026, 9, 20), date(2026, 9, 21)),  # Sunday -> Monday
        (date(2026, 10, 20), date(2026, 10, 20)),  # a Tuesday stays
        (date(2026, 12, 25), date(2026, 12, 28)),  # Christmas, St Stephen's, Sunday -> Monday
        (date(2026, 4, 5), date(2026, 4, 7)),  # Easter Sunday and Monday
    ],
)
def test_next_business_day(due: date, expected: date) -> None:
    assert next_business_day(due) == expected
