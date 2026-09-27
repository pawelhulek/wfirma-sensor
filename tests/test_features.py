"""Cost invoices, tax deadlines, the calendar and the two actions, end to end with a mocked client."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wfirma.const import DOMAIN
from custom_components.wfirma.deadlines import TaxPayment, TaxProfile
from custom_components.wfirma.diagnostics import async_get_config_entry_diagnostics
from custom_components.wfirma.exceptions import (
    WfirmaAuthError,
    WfirmaConnectionError,
    WfirmaNotFoundError,
)
from custom_components.wfirma.expenses import Expense
from custom_components.wfirma.models import Invoice

from .builders import expense_dict, invoice_dict, payment_dict
from .test_init import DATA

CLIENT = "custom_components.wfirma.WfirmaClient"
PDF = b"%PDF-1.7 test"


def zus(paid_on: str) -> TaxPayment:
    p = TaxPayment.from_api(payment_dict(date=paid_on, value="1926.76", social="1400.00", health="526.76"))
    assert p is not None
    return p


INVOICES = (Invoice.from_api(invoice_dict(id="1", fullnumber="FV 1", paymentdate="2026-10-03")),)
EXPENSES = (
    Expense.from_api(expense_dict(id="5", fullnumber="FZ 5", payment_date="2026-09-20", remaining="100.00")),
    Expense.from_api(expense_dict(id="6", fullnumber="FZ 6", payment_date="2026-10-05", remaining="23.00")),
)
PAYMENTS = (zus("2026-07-16"), zus("2026-08-13"))
PROFILE = TaxProfile(income_tax="lumpregister", vat_payer=True)


@pytest.fixture(autouse=True)
def frozen(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    freezer.move_to("2026-09-27 12:00:00+02:00")
    return freezer


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    e = MockConfigEntry(domain=DOMAIN, unique_id="4242", title="Hulek IT", data=DATA)
    e.add_to_hass(hass)
    return e


@pytest.fixture
def api():
    mocks = {
        "unpaid_invoices": AsyncMock(return_value=INVOICES),
        "invoices_issued_since": AsyncMock(return_value=INVOICES),
        "get_invoice": AsyncMock(),
        "unpaid_expenses": AsyncMock(return_value=EXPENSES),
        "tax_payments_since": AsyncMock(return_value=PAYMENTS),
        "company_profile": AsyncMock(return_value=PROFILE),
        "find_invoice": AsyncMock(return_value=INVOICES[0]),
        "download_invoice": AsyncMock(return_value=PDF),
    }
    patches = [patch(f"{CLIENT}.{name}", mock) for name, mock in mocks.items()]
    for p in patches:
        p.start()
    yield type("Api", (), mocks)
    for p in patches:
        p.stop()


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def entity_id(hass: HomeAssistant, domain: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"4242_{key}")


def state(hass: HomeAssistant, key: str, domain: str = "sensor"):
    eid = entity_id(hass, domain, key)
    assert eid, key
    return hass.states.get(eid)


async def test_cost_invoice_sensors(hass: HomeAssistant, entry, api) -> None:
    await setup(hass, entry)
    assert state(hass, "unpaid_expenses").state == "2"
    assert Decimal(state(hass, "unpaid_expenses_amount").state) == Decimal("123.00")
    attrs = state(hass, "unpaid_expenses").attributes
    assert attrs["overdue"] == 1
    assert attrs["next_due"] == "2026-09-20"
    assert [e["number"] for e in attrs["expenses"]] == ["FZ 5", "FZ 6"]


async def test_zus_sensor_shows_the_overdue_month(hass: HomeAssistant, entry, api) -> None:
    await setup(hass, entry)
    zus_state = state(hass, "next_zus_payment")
    assert zus_state.state == "2026-09-21"
    assert zus_state.attributes["period"] == "2026-08"
    assert zus_state.attributes["overdue"] is True
    assert zus_state.attributes["paid"] is False
    assert zus_state.attributes["days_left"] == -6
    assert zus_state.attributes["estimated_amount"] == 1926.76
    assert zus_state.attributes["last_payment_date"] == "2026-08-13"


async def test_tax_sensors(hass: HomeAssistant, entry, api) -> None:
    await setup(hass, entry)
    income = state(hass, "next_income_tax_payment")
    assert income.state == "2026-10-20"
    assert income.attributes["tax_form"] == "lumpregister"
    assert income.attributes["paid"] is None
    assert state(hass, "next_vat_payment").state == "2026-10-26"


async def test_no_vat_sensor_for_a_non_vat_payer(hass: HomeAssistant, entry, api) -> None:
    api.company_profile.return_value = TaxProfile(income_tax="lumpregister", vat_payer=False)
    await setup(hass, entry)
    assert entity_id(hass, "sensor", "next_vat_payment") is None


async def test_optional_data_failing_keeps_the_invoice_sensors(hass: HomeAssistant, entry, api) -> None:
    api.unpaid_expenses.side_effect = WfirmaAuthError("ACCESS DENIED")  # keys without the expenses module
    api.tax_payments_since.side_effect = WfirmaConnectionError("down")
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert not hass.config_entries.flow.async_progress()  # not treated as bad keys
    assert state(hass, "unpaid_invoices").state == "1"
    assert state(hass, "unpaid_expenses").state == "unavailable"
    # Without payment history the ZUS status is unknown, so the next deadline is simply the next one.
    assert state(hass, "next_zus_payment").state == "2026-10-20"


async def test_profile_failing_makes_deadlines_unavailable(hass: HomeAssistant, entry, api) -> None:
    api.company_profile.side_effect = WfirmaConnectionError("down")
    await setup(hass, entry)
    assert state(hass, "next_zus_payment").state == "unavailable"
    assert state(hass, "unpaid_expenses").state == "2"


async def test_calendar_lists_deadlines_and_payments(hass: HomeAssistant, entry, api) -> None:
    hass.config.language = "pl"
    await setup(hass, entry)
    cal = entity_id(hass, "calendar", "calendar")
    assert cal
    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {"entity_id": cal, "start_date_time": "2026-09-01 00:00:00", "end_date_time": "2026-10-31 00:00:00"},
        blocking=True,
        return_response=True,
    )
    summaries = [e["summary"] for e in result[cal]["events"]]
    assert "ZUS za 08.2026" in summaries
    assert "✅ ZUS za 07.2026" not in summaries  # due 20 Aug, outside the range
    assert "Ryczałt za 09.2026" in summaries
    assert "VAT (JPK_V7M) za 09.2026" in summaries
    assert "Zapłać: FZ 5 (Orange Polska S.A.)" in summaries
    assert "Wpłata: FV 1 (ACME Sp. z o.o.)" in summaries
    assert state(hass, "calendar", "calendar").state in ("on", "off")


async def test_get_documents_action(hass: HomeAssistant, entry, api) -> None:
    await setup(hass, entry)
    result = await hass.services.async_call(DOMAIN, "get_documents", {}, blocking=True, return_response=True)
    assert [i["number"] for i in result["unpaid_invoices"]] == ["FV 1"]
    assert [e["number"] for e in result["unpaid_expenses"]] == ["FZ 5", "FZ 6"]
    first = result["deadlines"][0]
    assert first == {"kind": "zus", "period": "2026-08", "due": "2026-09-21", "paid": False, "overdue": True}
    assert all(d["due"] <= "2026-12-31" for d in result["deadlines"])


async def test_download_invoice_action(hass: HomeAssistant, entry, api, tmp_path: Path) -> None:
    hass.config.media_dirs = {"local": str(tmp_path)}
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    await setup(hass, entry)
    result = await hass.services.async_call(
        DOMAIN, "download_invoice", {"number": "FV 1"}, blocking=True, return_response=True
    )
    saved = tmp_path / "wfirma" / "FV_1.pdf"
    assert saved.read_bytes() == PDF
    assert result == {"number": "FV 1", "path": str(saved), "size": len(PDF)}
    api.download_invoice.assert_awaited_once_with("1")


async def test_download_unknown_invoice(hass: HomeAssistant, entry, api) -> None:
    api.find_invoice.return_value = None
    await setup(hass, entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "download_invoice", {"number": "FV 404"}, blocking=True, return_response=True
        )


async def test_download_failure(hass: HomeAssistant, entry, api, tmp_path: Path) -> None:
    hass.config.media_dirs = {"local": str(tmp_path)}
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    api.download_invoice.side_effect = WfirmaNotFoundError("NOT FOUND")
    await setup(hass, entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "download_invoice", {"number": "FV 1"}, blocking=True, return_response=True
        )


async def test_download_outside_allowed_dirs(hass: HomeAssistant, entry, api, tmp_path: Path) -> None:
    hass.config.media_dirs = {"local": str(tmp_path)}
    hass.config.allowlist_external_dirs = set()
    await setup(hass, entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "download_invoice", {"number": "FV 1"}, blocking=True, return_response=True
        )


async def test_actions_need_a_choice_with_two_companies(hass: HomeAssistant, entry, api) -> None:
    other = MockConfigEntry(domain=DOMAIN, unique_id="5151", title="Other", data={**DATA, "company_id": "5151"})
    other.add_to_hass(hass)
    await setup(hass, entry)  # loads every wFirma entry
    assert other.state is ConfigEntryState.LOADED
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "get_documents", {}, blocking=True, return_response=True)
    result = await hass.services.async_call(
        DOMAIN, "get_documents", {"config_entry_id": other.entry_id}, blocking=True, return_response=True
    )
    assert result["unpaid_invoices"]


async def test_diagnostics_include_the_new_totals(hass: HomeAssistant, entry, api) -> None:
    await setup(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["expenses"] == {"unpaid_count": 2, "overdue_count": 1, "unpaid_amount": 123.0}
    assert diag["tax_profile"] == {"income_tax": "lumpregister", "vat_payer": True}
    assert {"kind": "zus", "due": "2026-09-21", "paid": False} in diag["deadlines"]
    assert diag["tax_payments"] == 2
    assert "Orange" not in str(diag)


async def test_profile_is_fetched_once(hass: HomeAssistant, entry, api, frozen) -> None:
    await setup(hass, entry)
    await entry.runtime_data.async_refresh()
    assert api.company_profile.await_count == 1
    assert api.tax_payments_since.await_args.args[0] == date(2025, 8, 23)
