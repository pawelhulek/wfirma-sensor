"""Immutable views of the wFirma records this integration reads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .const import BASE_CURRENCY, NON_SALES_TYPES

_ZERO = Decimal("0")


def _decimal(value: Any) -> Decimal:
    """wFirma sends amounts as strings like "1230.00"; anything unreadable counts as zero."""
    if value is None or value == "":
        return _ZERO
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return _ZERO


def _date(value: Any) -> date | None:
    """Dates are "YYYY-MM-DD"; wFirma uses "0000-00-00" for none."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


@dataclass(frozen=True, slots=True)
class Invoice:
    """One wFirma sales or pro-forma document."""

    id: str
    number: str
    issue_date: date | None
    due_date: date | None
    gross: Decimal
    net: Decimal
    remaining: Decimal
    currency: str
    doc_type: str
    payment_state: str
    contractor: str

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> Invoice:
        """Build from an API record; field names per the wFirma invoices module."""
        invoice_id = _text(raw.get("id"))
        contractor = raw.get("contractor_detail") or {}
        if not isinstance(contractor, Mapping):
            contractor = {}
        return cls(
            id=invoice_id,
            number=_text(raw.get("fullnumber")) or invoice_id,
            issue_date=_date(raw.get("date")),
            due_date=_date(raw.get("paymentdate")),
            gross=_decimal(raw.get("total")),
            net=_decimal(raw.get("netto")),
            remaining=_decimal(raw.get("remaining")),
            currency=_text(raw.get("currency")).upper() or BASE_CURRENCY,
            doc_type=_text(raw.get("type")) or "normal",
            payment_state=_text(raw.get("paymentstate")) or "undefined",
            contractor=_text(contractor.get("name")) or _text(contractor.get("altname")),
        )

    @property
    def is_sales(self) -> bool:
        """Pro-formas, offers and drafts are not sales."""
        return self.doc_type not in NON_SALES_TYPES

    @property
    def is_unpaid(self) -> bool:
        return self.is_sales and self.remaining > _ZERO

    def is_overdue(self, today: date) -> bool:
        return self.is_unpaid and self.due_date is not None and self.due_date < today

    def as_attribute(self) -> dict[str, Any]:
        """A small JSON-serialisable view for entity attributes."""
        return {
            "number": self.number,
            "contractor": self.contractor,
            "remaining": float(self.remaining),
            "currency": self.currency,
            "due_date": self.due_date.isoformat() if self.due_date else None,
        }


@dataclass(frozen=True, slots=True)
class Company:
    """A company the API keys can access."""

    id: str
    name: str

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> Company | None:
        """user_companies records may be a relation: prefer the explicit company_* fields."""
        company_id = _text(raw.get("company_id")) or _text(raw.get("id"))
        name = _text(raw.get("company_name")) or _text(raw.get("name")) or _text(raw.get("altname"))
        if not company_id.isdigit():
            return None
        return cls(id=company_id, name=name or f"wFirma {company_id}")
