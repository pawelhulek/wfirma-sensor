"""Polls wFirma, summarises, and announces invoices that became paid."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import WfirmaClient
from .const import (
    CONF_COMPANY_NAME,
    DOMAIN,
    EVENT_INVOICE_PAID,
    SCAN_INTERVAL,
    TAX_PAYMENT_LOOKBACK,
)
from .deadlines import Deadline, TaxPayment, TaxProfile, build_deadlines
from .exceptions import WfirmaAuthError, WfirmaError
from .expenses import ExpenseSummary, summarize_expenses
from .models import Invoice
from .summary import Summary, settled_since, summarize

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Everything one poll learned. Optional parts are None when wFirma would not give them."""

    today: date
    invoices: Summary
    expenses: ExpenseSummary | None
    profile: TaxProfile | None
    tax_payments: tuple[TaxPayment, ...] | None
    deadlines: tuple[Deadline, ...] | None


class WfirmaCoordinator(DataUpdateCoordinator[Snapshot]):
    """One coordinator per wFirma company."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: WfirmaClient) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.client = client
        self._previous_unpaid: frozenset[str] | None = None
        self._profile: TaxProfile | None = None
        self._failing: set[str] = set()

    async def _async_update_data(self) -> Snapshot:
        today = dt_util.now().date()
        try:
            unpaid = await self.client.unpaid_invoices()
            issued = await self.client.invoices_issued_since(today.replace(day=1))
        except WfirmaAuthError as err:
            raise ConfigEntryAuthFailed("wFirma rejected the API keys") from err
        except WfirmaError as err:
            raise UpdateFailed(f"wFirma update failed: {err}") from err

        summary = summarize(unpaid, issued, today)
        retry: frozenset[str] = frozenset()
        if self._previous_unpaid is not None:
            retry = await self._announce_paid(settled_since(self._previous_unpaid, summary))
        # Invoices we could not look up stay "previously unpaid", so the next poll retries them.
        self._previous_unpaid = summary.unpaid_ids | retry

        expenses = await self._optional("cost invoices", self.client.unpaid_expenses)
        if self._profile is None:  # tax settings change about once a year: fetch once per start
            self._profile = await self._optional("company tax settings", self.client.company_profile)
        payments = await self._optional(
            "tax payments", lambda: self.client.tax_payments_since(today - TAX_PAYMENT_LOOKBACK)
        )
        deadlines = build_deadlines(self._profile, payments or (), today) if self._profile else None
        return Snapshot(
            today=today,
            invoices=summary,
            expenses=summarize_expenses(expenses, today) if expenses is not None else None,
            profile=self._profile,
            tax_payments=payments,
            deadlines=deadlines,
        )

    async def _optional[T](self, what: str, fetch: Callable[[], Awaitable[T]]) -> T | None:
        """Extras must never take the invoice sensors down.

        An ACCESS DENIED here usually means the keys lack that module, not that they
        are wrong, so it is not escalated to re-authentication.
        """
        try:
            result = await fetch()
        except WfirmaError as err:
            log = _LOGGER.debug if what in self._failing else _LOGGER.warning
            log("wFirma %s unavailable: %s", what, err)
            self._failing.add(what)
            return None
        self._failing.discard(what)
        return result

    async def _announce_paid(self, candidate_ids: Iterable[str]) -> frozenset[str]:
        """Fire an event only for invoices wFirma confirms are settled.

        An invoice can also leave the unpaid list by being deleted or turned into a
        draft, so each one is looked up before it is announced. Returns the ids
        whose lookup failed.
        """
        failed: set[str] = set()
        for invoice_id in sorted(candidate_ids):
            try:
                invoice = await self.client.get_invoice(invoice_id)
            except (WfirmaError, ValueError) as err:
                _LOGGER.debug("Could not confirm payment of invoice %s: %s", invoice_id, err)
                failed.add(invoice_id)
                continue
            if invoice is None or not invoice.is_sales or invoice.is_unpaid:
                continue
            self.hass.bus.async_fire(EVENT_INVOICE_PAID, self._event_data(invoice))
        return frozenset(failed)

    def _event_data(self, invoice: Invoice) -> dict[str, Any]:
        entry = self.config_entry
        return {
            "invoice_id": invoice.id,
            "number": invoice.number,
            "contractor": invoice.contractor,
            "amount": float(invoice.gross),
            "currency": invoice.currency,
            "company": entry.data.get(CONF_COMPANY_NAME) or entry.title,
        }


type WfirmaConfigEntry = ConfigEntry[WfirmaCoordinator]
