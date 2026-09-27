"""Monthly ZUS, income-tax and VAT deadlines for a sole trader.

The wFirma API does not expose upcoming tax amounts or deadlines, so they are
derived from the statutory calendar and the company's tax settings. Payments
recorded against declarations tell ZUS apart (they carry the contribution
split); income tax and VAT payments look alike, so their status stays unknown.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from .holidays_pl import next_business_day
from .parsing import ZERO, to_date, to_decimal, to_flag, to_text

MONTHS_BACK = 2
MONTHS_AHEAD = 12

# wFirma "tax" values -> day of the following month the income tax is due.
_INCOME_TAX_DAY: Mapping[str, int] = {"lumpregister": 20, "linear": 20, "scale": 20, "card": 7}
_ZUS_DAY = 20
_VAT_DAY = 25  # JPK_V7M, monthly filers
_CARD_DECEMBER_DAY = 28  # the tax card's December instalment is due in December


class DeadlineKind(StrEnum):
    ZUS = "zus"
    INCOME_TAX = "income_tax"
    VAT = "vat"


@dataclass(frozen=True, slots=True)
class TaxProfile:
    """What the company pays, from wFirma's company settings."""

    income_tax: str
    vat_payer: bool

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> TaxProfile:
        return cls(income_tax=to_text(raw.get("tax")), vat_payer=to_flag(raw.get("vat_payer")))

    @property
    def kinds(self) -> tuple[DeadlineKind, ...]:
        income = (DeadlineKind.INCOME_TAX,) if self.income_tax in _INCOME_TAX_DAY else ()
        vat = (DeadlineKind.VAT,) if self.vat_payer else ()
        return (DeadlineKind.ZUS, *income, *vat)


@dataclass(frozen=True, slots=True)
class TaxPayment:
    """A payment wFirma recorded against a declaration."""

    paid_on: date
    amount: Decimal
    is_zus: bool

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> TaxPayment | None:
        paid_on = to_date(raw.get("date"))
        if paid_on is None:
            return None
        parts = (to_decimal(raw.get(k)) for k in ("social", "health", "labor_fund"))
        return cls(paid_on=paid_on, amount=to_decimal(raw.get("value")), is_zus=any(p > ZERO for p in parts))


@dataclass(frozen=True, slots=True)
class Deadline:
    """One payment due for one settlement month."""

    kind: DeadlineKind
    period: date  # first day of the month being settled
    due: date
    paid: bool | None  # None: wFirma's records cannot tell

    def days_left(self, today: date) -> int:
        return (self.due - today).days

    def is_overdue(self, today: date) -> bool:
        return self.paid is False and self.due < today


def _add_months(first_of_month: date, months: int) -> date:
    index = first_of_month.year * 12 + first_of_month.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _same_day(day: date, months: int) -> date:
    """The same day of the month `months` away, clamped to that month's length."""
    first = _add_months(day.replace(day=1), months)
    last_day = (_add_months(first, 1) - timedelta(days=1)).day
    return first.replace(day=min(day.day, last_day))


def statutory_due(kind: DeadlineKind, period: date, profile: TaxProfile) -> date:
    """Due date for the month starting at `period`, moved off weekends and holidays."""
    following = _add_months(period, 1)
    if kind is DeadlineKind.ZUS:
        day = _ZUS_DAY
    elif kind is DeadlineKind.VAT:
        day = _VAT_DAY
    elif profile.income_tax == "card" and period.month == 12:
        return next_business_day(period.replace(day=_CARD_DECEMBER_DAY))
    else:
        # December income tax may also be settled with the annual return; the earlier date is the safe one.
        day = _INCOME_TAX_DAY.get(profile.income_tax, _ZUS_DAY)
    return next_business_day(following.replace(day=day))


def _zus_paid_periods(payments: Iterable[TaxPayment]) -> frozenset[date]:
    """A ZUS payment made in month X settles month X-1."""
    return frozenset(_add_months(p.paid_on.replace(day=1), -1) for p in payments if p.is_zus)


def build_deadlines(profile: TaxProfile, payments: Iterable[TaxPayment], today: date) -> tuple[Deadline, ...]:
    """Deadlines due from about two months ago to a year ahead, soonest first."""
    paid_periods = _zus_paid_periods(payments)
    this_month = today.replace(day=1)
    earliest, latest = _same_day(today, -MONTHS_BACK), _same_day(today, MONTHS_AHEAD)
    deadlines: list[Deadline] = []
    for offset in range(-MONTHS_BACK - 1, MONTHS_AHEAD + 1):
        period = _add_months(this_month, offset)
        for kind in profile.kinds:
            due = statutory_due(kind, period, profile)
            if not earliest <= due <= latest:
                continue
            paid: bool | None = None
            if kind is DeadlineKind.ZUS and paid_periods:
                paid = period in paid_periods
            deadlines.append(Deadline(kind, period, due, paid))
    return tuple(sorted(deadlines, key=lambda d: (d.due, d.kind)))


def next_deadline(deadlines: Iterable[Deadline], kind: DeadlineKind, today: date) -> Deadline | None:
    """The oldest unpaid deadline (overdue included), else the first one not yet past."""
    candidates = [d for d in deadlines if d.kind is kind and d.paid is not True]
    overdue = [d for d in candidates if d.is_overdue(today)]
    upcoming = [d for d in candidates if d.due >= today]
    pool = overdue or upcoming
    return min(pool, key=lambda d: d.due) if pool else None


def last_payment(payments: Iterable[TaxPayment], *, zus: bool) -> TaxPayment | None:
    """The most recent ZUS payment (zus=True) or tax payment (zus=False)."""
    matching = [p for p in payments if p.is_zus is zus]
    return max(matching, key=lambda p: p.paid_on) if matching else None
