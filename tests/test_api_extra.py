"""The client's cost-invoice, tax, company-profile and PDF calls."""

from datetime import date

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.wfirma.api import WfirmaClient
from custom_components.wfirma.deadlines import TaxProfile
from custom_components.wfirma.exceptions import WfirmaNotFoundError, WfirmaResponseError

from .builders import api_payload, expense_dict, invoice_dict, payment_dict, status_payload

BASE = "https://api2.wfirma.pl"
PDF = b"%PDF-1.7\n...\n%%EOF"


def client(hass: HomeAssistant) -> WfirmaClient:
    return WfirmaClient(async_get_clientsession(hass), "acc", "sec", "app", "4242")


def condition(aioclient_mock: AiohttpClientMocker, module: str) -> dict:
    return aioclient_mock.mock_calls[0][2][module]["parameters"]["conditions"]["condition"]


async def test_unpaid_expenses(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(f"{BASE}/expenses/find", json=api_payload("expenses", "expense", [expense_dict(id="7")]))
    expenses = await client(hass).unpaid_expenses()
    assert [e.id for e in expenses] == ["7"]
    assert condition(aioclient_mock, "expenses") == {"field": "Expense.remaining", "operator": "gt", "value": "0"}


async def test_tax_payments_since(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    records = [
        payment_dict(id="1", date="2026-09-15"),
        payment_dict(id="2", date="2026-01-10"),  # older than asked: dropped
        payment_dict(id="3", date="0000-00-00"),  # unreadable: dropped
        payment_dict(id="4", date="2026-09-01", object_name="invoice"),  # not a declaration: dropped
    ]
    aioclient_mock.post(f"{BASE}/payments/find", json=api_payload("payments", "payment", records))
    payments = await client(hass).tax_payments_since(date(2026, 6, 1))
    assert [p.paid_on for p in payments] == [date(2026, 9, 15)]
    assert condition(aioclient_mock, "payments") == {
        "field": "Payment.object_name",
        "operator": "eq",
        "value": "declaration_header",
    }


async def test_company_profile(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    record = {"id": "4242", "name": "Hulek IT", "tax": "lumpregister", "vat_payer": "1"}
    aioclient_mock.post(f"{BASE}/companies/find", json=api_payload("companies", "company", [record]))
    assert await client(hass).company_profile() == TaxProfile(income_tax="lumpregister", vat_payer=True)


async def test_company_profile_missing(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(f"{BASE}/companies/find", json=api_payload("companies", "company", []))
    with pytest.raises(WfirmaNotFoundError):
        await client(hass).company_profile()


async def test_find_invoice_by_number(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(
        f"{BASE}/invoices/find",
        json=api_payload("invoices", "invoice", [invoice_dict(id="9", fullnumber="FV 3/9/2026")]),
    )
    found = await client(hass).find_invoice("FV 3/9/2026")
    assert found is not None and found.id == "9"
    assert condition(aioclient_mock, "invoices") == {
        "field": "Invoice.fullnumber",
        "operator": "eq",
        "value": "FV 3/9/2026",
    }


async def test_find_invoice_ignores_near_matches(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(
        f"{BASE}/invoices/find", json=api_payload("invoices", "invoice", [invoice_dict(fullnumber="FV 3/9/2026 K")])
    )
    assert await client(hass).find_invoice("FV 3/9/2026") is None


async def test_download_invoice(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(f"{BASE}/invoices/download/9", content=PDF, headers={"Content-Type": "application/pdf"})
    assert await client(hass).download_invoice("9") == PDF


async def test_download_error_status(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(f"{BASE}/invoices/download/9", json=status_payload("NOT FOUND"))
    with pytest.raises(WfirmaNotFoundError):
        await client(hass).download_invoice("9")


async def test_download_that_is_not_a_pdf(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(f"{BASE}/invoices/download/9", json={"status": {"code": "OK"}})
    with pytest.raises(WfirmaResponseError):
        await client(hass).download_invoice("9")


async def test_download_rejects_non_numeric_ids(hass: HomeAssistant) -> None:
    with pytest.raises(ValueError):
        await client(hass).download_invoice("9/../../companies")
