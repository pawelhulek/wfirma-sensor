"""Setup, sensors, the paid event, diagnostics and unload — end to end with a mocked client."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.wfirma.const import (
    CONF_ACCESS_KEY,
    CONF_APP_KEY,
    CONF_COMPANY_ID,
    CONF_COMPANY_NAME,
    CONF_SECRET_KEY,
    DOMAIN,
    EVENT_INVOICE_PAID,
    SCAN_INTERVAL,
)
from custom_components.wfirma.deadlines import TaxProfile
from custom_components.wfirma.diagnostics import async_get_config_entry_diagnostics
from custom_components.wfirma.exceptions import (
    WfirmaAuthError,
    WfirmaConnectionError,
    WfirmaRateLimitError,
)
from custom_components.wfirma.models import Invoice

from .builders import invoice_dict

CLIENT = "custom_components.wfirma.WfirmaClient"
DATA = {
    CONF_ACCESS_KEY: "acc",
    CONF_SECRET_KEY: "sec",
    CONF_APP_KEY: "app",
    CONF_COMPANY_ID: "4242",
    CONF_COMPANY_NAME: "Hulek IT",
}


def inv(**kw) -> Invoice:
    return Invoice.from_api(invoice_dict(**kw))


UNPAID = (
    inv(id="1", fullnumber="FV 1", remaining="1230.00", paymentdate="2026-09-01"),  # overdue
    inv(id="2", fullnumber="FV 2", remaining="615.00", paymentdate="2026-10-15"),
)
ISSUED = (
    inv(id="1", netto="1000.00", total="1230.00", date="2026-09-02"),
    inv(id="2", netto="500.00", total="615.00", date="2026-09-20"),
)


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    e = MockConfigEntry(domain=DOMAIN, unique_id="4242", title="Hulek IT", data=DATA)
    e.add_to_hass(hass)
    return e


@pytest.fixture
def api():
    with patch(f"{CLIENT}.unpaid_invoices", AsyncMock(return_value=UNPAID)) as unpaid, patch(
        f"{CLIENT}.invoices_issued_since", AsyncMock(return_value=ISSUED)
    ) as issued, patch(f"{CLIENT}.get_invoice", AsyncMock()) as get, patch(
        f"{CLIENT}.unpaid_expenses", AsyncMock(return_value=())
    ), patch(f"{CLIENT}.tax_payments_since", AsyncMock(return_value=())), patch(
        f"{CLIENT}.company_profile", AsyncMock(return_value=TaxProfile(income_tax="lumpregister", vat_payer=True))
    ):
        yield type("Api", (), {"unpaid": unpaid, "issued": issued, "get": get})


@pytest.fixture(autouse=True)
def frozen_today(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    freezer.move_to("2026-09-25 12:00:00+02:00")
    return freezer


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def state(hass: HomeAssistant, key: str):
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"4242_{key}")
    assert entity_id, key
    return hass.states.get(entity_id)


async def test_sensors_show_the_summary(hass: HomeAssistant, entry, api) -> None:
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    assert state(hass, "unpaid_invoices").state == "2"
    assert Decimal(state(hass, "unpaid_amount").state) == Decimal("1845.00")
    assert state(hass, "unpaid_amount").attributes["unit_of_measurement"] == "PLN"
    assert state(hass, "overdue_invoices").state == "1"
    assert Decimal(state(hass, "overdue_amount").state) == Decimal("1230.00")
    assert Decimal(state(hass, "revenue_month_net").state) == Decimal("1500.00")
    assert Decimal(state(hass, "revenue_month_gross").state) == Decimal("1845.00")

    attrs = state(hass, "overdue_invoices").attributes
    assert attrs["invoices"][0]["number"] == "FV 1"
    api.issued.assert_awaited_with(__import__("datetime").date(2026, 9, 1))


async def test_entities_share_one_service_device(hass: HomeAssistant, entry, api) -> None:
    await setup(hass, entry)
    ids = {e.device_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
    assert len(ids) == 1


async def test_bad_keys_at_startup_start_reauth(hass: HomeAssistant, entry, api) -> None:
    api.unpaid.side_effect = WfirmaAuthError("AUTH")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


@pytest.mark.parametrize("error", [WfirmaConnectionError("down"), WfirmaRateLimitError("limit")])
async def test_temporary_failures_retry_later(hass: HomeAssistant, entry, api, error) -> None:
    api.unpaid.side_effect = error
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress()


async def test_failure_after_start_marks_sensors_unavailable(
    hass: HomeAssistant, entry, api, frozen_today: FrozenDateTimeFactory
) -> None:
    await setup(hass, entry)
    api.unpaid.side_effect = WfirmaConnectionError("down")
    frozen_today.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert state(hass, "unpaid_invoices").state == "unavailable"


async def test_paid_invoice_fires_an_event(hass: HomeAssistant, entry, api, frozen_today) -> None:
    events = async_capture_events(hass, EVENT_INVOICE_PAID)
    await setup(hass, entry)
    assert events == []  # nothing to compare against on the first poll

    api.unpaid.return_value = (UNPAID[1],)
    api.get.return_value = inv(id="1", fullnumber="FV 1", remaining="0.00", paymentstate="paid", total="1230.00")
    frozen_today.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data == {
        "invoice_id": "1",
        "number": "FV 1",
        "contractor": "ACME Sp. z o.o.",
        "amount": 1230.0,
        "currency": "PLN",
        "company": "Hulek IT",
    }
    api.get.assert_awaited_once_with("1")


@pytest.mark.parametrize(
    "lookup",
    [None, inv(id="1", remaining="100.00"), WfirmaConnectionError("down")],
    ids=["deleted", "still-unpaid", "lookup-failed"],
)
async def test_no_event_unless_payment_is_confirmed(hass: HomeAssistant, entry, api, frozen_today, lookup) -> None:
    events = async_capture_events(hass, EVENT_INVOICE_PAID)
    await setup(hass, entry)
    api.unpaid.return_value = (UNPAID[1],)
    if isinstance(lookup, Exception):
        api.get.side_effect = lookup
    else:
        api.get.return_value = lookup
    frozen_today.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert events == []


async def test_unload(hass: HomeAssistant, entry, api) -> None:
    await setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics_hide_keys_and_client_names(hass: HomeAssistant, entry, api) -> None:
    await setup(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diag)
    for secret in ("acc", "sec", "app"):
        assert f"'{secret}'" not in text
    assert "ACME" not in text
    assert diag["summary"]["unpaid_count"] == 2


async def test_failed_confirmation_is_retried_next_poll(hass: HomeAssistant, entry, api, frozen_today) -> None:
    events = async_capture_events(hass, EVENT_INVOICE_PAID)
    await setup(hass, entry)
    api.unpaid.return_value = (UNPAID[1],)
    api.get.side_effect = WfirmaRateLimitError("TOTAL REQUESTS LIMIT EXCEEDED")
    frozen_today.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert events == []

    api.get.side_effect = None
    api.get.return_value = inv(id="1", fullnumber="FV 1", remaining="0.00", paymentstate="paid")
    frozen_today.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [e.data["invoice_id"] for e in events] == ["1"]
