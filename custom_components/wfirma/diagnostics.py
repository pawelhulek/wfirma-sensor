"""Diagnostics: configuration and totals, without keys or client names."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_ACCESS_KEY, CONF_APP_KEY, CONF_SECRET_KEY
from .coordinator import WfirmaConfigEntry

TO_REDACT = {CONF_ACCESS_KEY, CONF_SECRET_KEY, CONF_APP_KEY}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: WfirmaConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    summary = coordinator.data
    totals = None
    if summary is not None:
        totals = {
            "currency": summary.currency,
            "unpaid_count": summary.unpaid_count,
            "unpaid_amount": float(summary.unpaid_amount),
            "overdue_count": summary.overdue_count,
            "overdue_amount": float(summary.overdue_amount),
            "revenue_count": summary.revenue_count,
            "revenue_net": float(summary.revenue_net),
            "revenue_gross": float(summary.revenue_gross),
            "other_currencies": sorted(
                set(summary.unpaid_other_currencies) | set(summary.revenue_other_currencies)
            ),
        }
    return {
        "entry": {"title": entry.title, "data": async_redact_data(dict(entry.data), TO_REDACT)},
        "last_update_success": coordinator.last_update_success,
        "summary": totals,
    }
