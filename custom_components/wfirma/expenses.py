"""Cost invoices (wFirma "expenses"): the bills the company has to pay."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from .const import ATTRIBUTE_LIST_LIMIT, BASE_CURRENCY
from .parsing import ZERO, contractor_name, to_date, to_decimal, to_flag, to_text


@dataclass(frozen=True, slots=True)
class Expense:
    """One purchase document booked in wFirma."""

    id: str
    number: str
    contractor: str
    due_date: date | None
    gross: Decimal
    remaining: Decimal
    currency: str
    is_draft: bool
    is_rejected: bool

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> Expense:
        """Field names per the wFirma expenses module (note payment_date, brutto)."""
        expense_id = to_text(raw.get("id"))
        return cls(
            id=expense_id,
            number=to_text(raw.get("fullnumber")) or expense_id,
            contractor=contractor_name(raw),
            due_date=to_date(raw.get("payment_date")),
            gross=to_decimal(raw.get("brutto")),
            remaining=to_decimal(raw.get("remaining")),
            currency=to_text(raw.get("currency")).upper() or BASE_CURRENCY,
            is_draft=to_flag(raw.get("draft")),
            is_rejected=to_flag(raw.get("is_rejected")),
        )

    @property
    def is_unpaid(self) -> bool:
        """Drafts and rejected documents are not bills yet."""
        return not self.is_draft and not self.is_rejected and self.remaining > ZERO

    def is_overdue(self, today: date) -> bool:
        return self.is_unpaid and self.due_date is not None and self.due_date < today

    def as_attribute(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "contractor": self.contractor,
            "remaining": float(self.remaining),
            "currency": self.currency,
            "due_date": self.due_date.isoformat() if self.due_date else None,
        }


@dataclass(frozen=True, slots=True)
class ExpenseSummary:
    """Unpaid bills, soonest due first."""

    currency: str
    unpaid: tuple[Expense, ...]
    overdue: tuple[Expense, ...]
    unpaid_amount: Decimal
    other_currencies: Mapping[str, Decimal]

    @property
    def unpaid_count(self) -> int:
        return len(self.unpaid)

    @property
    def next_due(self) -> date | None:
        return next((e.due_date for e in self.unpaid if e.due_date is not None), None)

    def unpaid_attributes(self) -> list[dict[str, Any]]:
        return [e.as_attribute() for e in self.unpaid[:ATTRIBUTE_LIST_LIMIT]]


def summarize_expenses(candidates: Iterable[Expense], today: date, currency: str = BASE_CURRENCY) -> ExpenseSummary:
    """Filtered again here, so an over-broad API answer still gives correct figures."""
    unpaid = tuple(sorted((e for e in candidates if e.is_unpaid), key=lambda e: (e.due_date or date.max, e.number)))
    others: dict[str, Decimal] = {}
    for e in unpaid:
        if e.currency != currency:
            others[e.currency] = others.get(e.currency, ZERO) + e.remaining
    return ExpenseSummary(
        currency=currency,
        unpaid=unpaid,
        overdue=tuple(e for e in unpaid if e.is_overdue(today)),
        unpaid_amount=sum((e.remaining for e in unpaid if e.currency == currency), ZERO),
        other_currencies=MappingProxyType(others),
    )
