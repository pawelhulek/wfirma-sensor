"""Immutable views of the wFirma records this integration reads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from .const import BASE_CURRENCY, NON_SALES_TYPES
from .parsing import ZERO, contractor_name, to_date, to_decimal, to_text


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
        invoice_id = to_text(raw.get("id"))
        return cls(
            id=invoice_id,
            number=to_text(raw.get("fullnumber")) or invoice_id,
            issue_date=to_date(raw.get("date")),
            due_date=to_date(raw.get("paymentdate")),
            gross=to_decimal(raw.get("total")),
            net=to_decimal(raw.get("netto")),
            remaining=to_decimal(raw.get("remaining")),
            currency=to_text(raw.get("currency")).upper() or BASE_CURRENCY,
            doc_type=to_text(raw.get("type")) or "normal",
            payment_state=to_text(raw.get("paymentstate")) or "undefined",
            contractor=contractor_name(raw),
        )

    @property
    def is_sales(self) -> bool:
        """Pro-formas, offers and drafts are not sales."""
        return self.doc_type not in NON_SALES_TYPES

    @property
    def is_unpaid(self) -> bool:
        return self.is_sales and self.remaining > ZERO

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
        company_id = to_text(raw.get("company_id")) or to_text(raw.get("id"))
        name = to_text(raw.get("company_name")) or to_text(raw.get("name")) or to_text(raw.get("altname"))
        if not company_id.isdigit():
            return None
        return cls(id=company_id, name=name or f"wFirma {company_id}")
