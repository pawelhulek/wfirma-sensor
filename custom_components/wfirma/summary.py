"""Pure functions that turn invoices into the values the sensors show."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from .const import ATTRIBUTE_LIST_LIMIT, BASE_CURRENCY
from .models import Invoice

_ZERO = Decimal("0")


def _by_currency(invoices: Iterable[Invoice], amount: str, base: str) -> Mapping[str, Decimal]:
    """Totals per non-base currency, read-only."""
    totals: dict[str, Decimal] = {}
    for inv in invoices:
        if inv.currency != base:
            totals[inv.currency] = totals.get(inv.currency, _ZERO) + getattr(inv, amount)
    return MappingProxyType(totals)


def _sum(invoices: Iterable[Invoice], amount: str, base: str) -> Decimal:
    return sum((getattr(i, amount) for i in invoices if i.currency == base), _ZERO)


def _oldest_due_first(invoice: Invoice) -> tuple[date, str]:
    return (invoice.due_date or date.max, invoice.number)


@dataclass(frozen=True, slots=True)
class Summary:
    """Everything the sensors need, computed once per poll."""

    currency: str
    unpaid: tuple[Invoice, ...]
    overdue: tuple[Invoice, ...]
    unpaid_amount: Decimal
    overdue_amount: Decimal
    unpaid_other_currencies: Mapping[str, Decimal]
    overdue_other_currencies: Mapping[str, Decimal]
    revenue_net: Decimal
    revenue_gross: Decimal
    revenue_count: int
    revenue_other_currencies: Mapping[str, Decimal]

    @property
    def unpaid_count(self) -> int:
        return len(self.unpaid)

    @property
    def overdue_count(self) -> int:
        return len(self.overdue)

    @property
    def unpaid_ids(self) -> frozenset[str]:
        return frozenset(i.id for i in self.unpaid)

    def unpaid_attributes(self) -> list[dict[str, Any]]:
        return [i.as_attribute() for i in self.unpaid[:ATTRIBUTE_LIST_LIMIT]]

    def overdue_attributes(self) -> list[dict[str, Any]]:
        return [i.as_attribute() for i in self.overdue[:ATTRIBUTE_LIST_LIMIT]]


def summarize(
    unpaid_candidates: Iterable[Invoice],
    issued_this_month: Iterable[Invoice],
    today: date,
    currency: str = BASE_CURRENCY,
) -> Summary:
    """Build the summary.

    Everything is filtered again here, so a query the API answered too broadly
    (for example if it ignored a condition) still yields correct figures.
    """
    unpaid = tuple(sorted((i for i in unpaid_candidates if i.is_unpaid), key=_oldest_due_first))
    overdue = tuple(i for i in unpaid if i.is_overdue(today))
    month_start = today.replace(day=1)
    revenue = tuple(
        i
        for i in issued_this_month
        if i.is_sales and i.issue_date is not None and month_start <= i.issue_date <= today
    )
    base_revenue = tuple(i for i in revenue if i.currency == currency)
    return Summary(
        currency=currency,
        unpaid=unpaid,
        overdue=overdue,
        unpaid_amount=_sum(unpaid, "remaining", currency),
        overdue_amount=_sum(overdue, "remaining", currency),
        unpaid_other_currencies=_by_currency(unpaid, "remaining", currency),
        overdue_other_currencies=_by_currency(overdue, "remaining", currency),
        revenue_net=_sum(base_revenue, "net", currency),
        revenue_gross=_sum(base_revenue, "gross", currency),
        revenue_count=len(base_revenue),
        revenue_other_currencies=_by_currency(revenue, "gross", currency),
    )


def settled_since(previous_unpaid_ids: frozenset[str], current: Summary) -> frozenset[str]:
    """Invoices unpaid at the last poll that are not unpaid any more."""
    return previous_unpaid_ids - current.unpaid_ids
