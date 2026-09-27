"""Diagnostics: configuration and totals, without keys or counterparty names."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_ACCESS_KEY, CONF_APP_KEY, CONF_SECRET_KEY
from .coordinator import Snapshot, WfirmaConfigEntry

TO_REDACT = {CONF_ACCESS_KEY, CONF_SECRET_KEY, CONF_APP_KEY}


def _invoice_totals(data: Snapshot) -> dict[str, Any]:
    summary = data.invoices
    return {
        "currency": summary.currency,
        "unpaid_count": summary.unpaid_count,
        "unpaid_amount": float(summary.unpaid_amount),
        "overdue_count": summary.overdue_count,
        "overdue_amount": float(summary.overdue_amount),
        "revenue_count": summary.revenue_count,
        "revenue_net": float(summary.revenue_net),
        "revenue_gross": float(summary.revenue_gross),
        "other_currencies": sorted(set(summary.unpaid_other_currencies) | set(summary.revenue_other_currencies)),
    }


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: WfirmaConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    result: dict[str, Any] = {
        "entry": {"title": entry.title, "data": async_redact_data(dict(entry.data), TO_REDACT)},
        "last_update_success": coordinator.last_update_success,
        "summary": _invoice_totals(data) if data else None,
    }
    if data is None:
        return result
    expenses = data.expenses
    result["expenses"] = expenses and {
        "unpaid_count": expenses.unpaid_count,
        "overdue_count": len(expenses.overdue),
        "unpaid_amount": float(expenses.unpaid_amount),
    }
    profile = data.profile
    result["tax_profile"] = profile and {"income_tax": profile.income_tax, "vat_payer": profile.vat_payer}
    result["tax_payments"] = None if data.tax_payments is None else len(data.tax_payments)
    result["deadlines"] = None if data.deadlines is None else [
        {"kind": d.kind.value, "due": d.due.isoformat(), "paid": d.paid} for d in data.deadlines
    ]
    return result
