"""Polish public holidays (Act of 18 January 1951) and the tax next-business-day rule.

Kept in-house instead of pulling a dependency: the list is short and changes rarely
(Christmas Eve became a holiday from 2025).
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import cache

_FIXED: tuple[tuple[int, int], ...] = (
    (1, 1),  # New Year
    (1, 6),  # Epiphany
    (5, 1),  # Labour Day
    (5, 3),  # Constitution Day
    (8, 15),  # Assumption
    (11, 1),  # All Saints
    (11, 11),  # Independence Day
    (12, 25),  # Christmas
    (12, 26),  # St Stephen's Day
)
_CHRISTMAS_EVE_FROM = 2025
_SATURDAY = 5


def easter_sunday(year: int) -> date:
    """Gregorian Easter (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 - the algorithm's own name
    m = (a + 11 * h + 19 * l) // 433
    month, day = divmod(h + l - 7 * m + 90, 25)
    day = (h + l - 7 * m + 33 * month + 19) % 32
    return date(year, month, day)


@cache
def public_holidays(year: int) -> frozenset[date]:
    easter = easter_sunday(year)
    movable = (easter, easter + timedelta(days=1), easter + timedelta(days=49), easter + timedelta(days=60))
    fixed = tuple(date(year, month, day) for month, day in _FIXED)
    eve = (date(year, 12, 24),) if year >= _CHRISTMAS_EVE_FROM else ()
    return frozenset((*fixed, *movable, *eve))


def is_day_off(day: date) -> bool:
    """Saturdays, Sundays and public holidays."""
    return day.weekday() >= _SATURDAY or day in public_holidays(day.year)


def next_business_day(due: date) -> date:
    """Tax Ordinance art. 12 §5: a deadline on a day off moves to the next working day."""
    while is_day_off(due):
        due += timedelta(days=1)
    return due
