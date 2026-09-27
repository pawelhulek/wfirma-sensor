"""Readers for the loosely typed values wFirma sends (numbers and dates arrive as strings)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

ZERO = Decimal("0")


def to_decimal(value: Any) -> Decimal:
    """Amounts arrive like "1230.00"; anything unreadable counts as zero."""
    if value is None or value == "":
        return ZERO
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return ZERO


def to_date(value: Any) -> date | None:
    """Dates are "YYYY-MM-DD"; wFirma uses "0000-00-00" for none."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def to_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def to_flag(value: Any) -> bool:
    """Booleans arrive as "0"/"1"."""
    return to_text(value) not in ("", "0", "false", "False")


def contractor_name(raw: Mapping[str, Any]) -> str:
    """The counterparty as printed on the document."""
    contractor = raw.get("contractor_detail") or {}
    if not isinstance(contractor, Mapping):
        return ""
    return to_text(contractor.get("name")) or to_text(contractor.get("altname"))
