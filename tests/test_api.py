"""The wFirma API client: request shape, paging, parsing and every error path."""

from datetime import date

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.wfirma.api import WfirmaClient
from custom_components.wfirma.const import PAGE_LIMIT
from custom_components.wfirma.exceptions import (
    WfirmaAuthError,
    WfirmaConnectionError,
    WfirmaRateLimitError,
    WfirmaResponseError,
)

from .builders import api_payload, invoice_dict, status_payload

BASE = "https://api2.wfirma.pl"


def client(hass: HomeAssistant, company_id: str | None = None) -> WfirmaClient:
    return WfirmaClient(async_get_clientsession(hass), "acc", "sec", "app", company_id)


async def test_request_shape(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(f"{BASE}/invoices/find", json=api_payload("invoices", "invoice", []))

    await client(hass, "4242").unpaid_invoices()

    method, url, body, headers = aioclient_mock.mock_calls[0]
    assert method == "POST"
    assert url.query["inputFormat"] == "json"
    assert url.query["outputFormat"] == "json"
    assert url.query["company_id"] == "4242"
    assert headers["accessKey"] == "acc"
    assert headers["secretKey"] == "sec"
    assert headers["appKey"] == "app"
    params = body["invoices"]["parameters"]
    assert params["conditions"]["condition"] == {
        "field": "Invoice.remaining",
        "operator": "gt",
        "value": "0",
    }
    assert params["limit"] == PAGE_LIMIT


async def test_no_company_id_when_not_configured(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(f"{BASE}/invoices/find", json=api_payload("invoices", "invoice", []))
    await client(hass).unpaid_invoices()
    assert "company_id" not in aioclient_mock.mock_calls[0][1].query


async def test_parses_invoices_and_unwraps_api_envelope(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(
        f"{BASE}/invoices/find",
        json=api_payload("invoices", "invoice", [invoice_dict(id="1"), invoice_dict(id="2")], wrap=True),
    )
    invoices = await client(hass).unpaid_invoices()
    assert [i.id for i in invoices] == ["1", "2"]
    assert isinstance(invoices, tuple)


async def test_follows_pages_until_total(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    pages = {
        1: [invoice_dict(id=str(i)) for i in range(PAGE_LIMIT)],
        2: [invoice_dict(id="last")],
    }

    async def respond(method, url, data):
        page = data["invoices"]["parameters"]["page"]
        return AiohttpClientMockResponse(
            method, url, json=api_payload("invoices", "invoice", pages[page], total=PAGE_LIMIT + 1, page=page)
        )

    aioclient_mock.post(f"{BASE}/invoices/find", side_effect=respond)
    invoices = await client(hass).unpaid_invoices()
    assert len(invoices) == PAGE_LIMIT + 1
    assert aioclient_mock.call_count == 2


async def test_stops_at_page_cap(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    full = [invoice_dict(id=str(i)) for i in range(PAGE_LIMIT)]
    aioclient_mock.post(
        f"{BASE}/invoices/find", json=api_payload("invoices", "invoice", full, total=10_000)
    )
    await client(hass).unpaid_invoices()
    assert aioclient_mock.call_count == 20


async def test_empty_collection_shapes(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(f"{BASE}/invoices/find", json={"invoices": [], "status": {"code": "OK"}})
    assert await client(hass).unpaid_invoices() == ()


async def test_issued_since_uses_a_date_condition(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(f"{BASE}/invoices/find", json=api_payload("invoices", "invoice", [invoice_dict()]))
    invoices = await client(hass).invoices_issued_since(date(2026, 9, 1))
    assert len(invoices) == 1
    cond = aioclient_mock.mock_calls[0][2]["invoices"]["parameters"]["conditions"]["condition"]
    assert cond == {"field": "Invoice.date", "operator": "ge", "value": "2026-09-01"}


async def test_get_invoice(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(
        f"{BASE}/invoices/get/77",
        json=api_payload("invoices", "invoice", [invoice_dict(id="77", remaining="0.00", paymentstate="paid")]),
    )
    inv = await client(hass).get_invoice("77")
    assert inv is not None and inv.payment_state == "paid"


async def test_get_invoice_not_found_is_none(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(f"{BASE}/invoices/get/77", json=status_payload("NOT FOUND"))
    assert await client(hass).get_invoice("77") is None


async def test_get_invoice_rejects_non_numeric_ids(hass: HomeAssistant) -> None:
    with pytest.raises(ValueError):
        await client(hass).get_invoice("../companies")


async def test_list_companies_prefers_company_fields_and_dedupes(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    payload = {
        "user_companies": {
            "0": {"user_company": {"id": "9", "company_id": "4242", "company_name": "Hulek IT"}},
            "1": {"user_company": {"id": "10", "company": {"id": "5151", "name": "Client Sp. z o.o."}}},
            "2": {"user_company": {"id": "11", "company_id": "4242", "company_name": "Hulek IT"}},
            "parameters": {"total": "3"},
        },
        "status": {"code": "OK"},
    }
    aioclient_mock.post(f"{BASE}/user_companies/find", json=payload)
    companies = await client(hass).list_companies()
    assert [(c.id, c.name) for c in companies] == [("4242", "Hulek IT"), ("5151", "Client Sp. z o.o.")]


async def test_with_company_returns_a_new_client(hass: HomeAssistant) -> None:
    base = client(hass)
    scoped = base.with_company("4242")
    assert scoped is not base
    assert scoped.company_id == "4242"
    assert base.company_id is None


@pytest.mark.parametrize("code", ["AUTH", "ACCESS DENIED"])
async def test_bad_credentials(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, code: str) -> None:
    aioclient_mock.post(f"{BASE}/invoices/find", json=status_payload(code))
    with pytest.raises(WfirmaAuthError):
        await client(hass).unpaid_invoices()


@pytest.mark.parametrize("body", ["AUTH", "ACCESS DENIED", '"AUTH"'])
async def test_bad_credentials_as_bare_text(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, body: str
) -> None:
    aioclient_mock.post(f"{BASE}/invoices/find", text=body)
    with pytest.raises(WfirmaAuthError):
        await client(hass).unpaid_invoices()


@pytest.mark.parametrize("code", ["TOTAL REQUESTS LIMIT EXCEEDED", "AUTH FAILED LIMIT WAIT 5 MINUTES"])
async def test_rate_limits_are_not_auth_failures(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, code: str
) -> None:
    aioclient_mock.post(f"{BASE}/invoices/find", json=status_payload(code))
    with pytest.raises(WfirmaRateLimitError):
        await client(hass).unpaid_invoices()


async def test_rate_limit_as_bare_text(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(f"{BASE}/invoices/find", text="AUTH FAILED LIMIT WAIT 5 MINUTES")
    with pytest.raises(WfirmaRateLimitError):
        await client(hass).unpaid_invoices()


@pytest.mark.parametrize("code", ["ERROR", "FATAL", "ACTION NOT FOUND", "OUT OF SERVICE", ""])
async def test_other_status_codes(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, code: str) -> None:
    aioclient_mock.post(f"{BASE}/invoices/find", json=status_payload(code))
    with pytest.raises(WfirmaResponseError):
        await client(hass).unpaid_invoices()


async def test_unreadable_body(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(f"{BASE}/invoices/find", text="<html>maintenance</html>")
    with pytest.raises(WfirmaResponseError):
        await client(hass).unpaid_invoices()


@pytest.mark.parametrize("status", [401, 403])
async def test_http_auth_status(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status: int) -> None:
    aioclient_mock.post(f"{BASE}/invoices/find", status=status, text="")
    with pytest.raises(WfirmaAuthError):
        await client(hass).unpaid_invoices()


async def test_http_server_error(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(f"{BASE}/invoices/find", status=503, text="")
    with pytest.raises(WfirmaConnectionError):
        await client(hass).unpaid_invoices()


@pytest.mark.parametrize("exc", [aiohttp.ClientError(), TimeoutError()])
async def test_network_failures(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, exc: Exception) -> None:
    aioclient_mock.post(f"{BASE}/invoices/find", exc=exc)
    with pytest.raises(WfirmaConnectionError):
        await client(hass).unpaid_invoices()


async def test_verify_asks_for_a_single_record(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(f"{BASE}/invoices/find", json=api_payload("invoices", "invoice", []))
    await client(hass).verify()
    assert aioclient_mock.mock_calls[0][2]["invoices"]["parameters"]["limit"] == 1


async def test_list_companies_ignores_nested_users(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    payload = {
        "user_companies": {
            "0": {"user_company": {"company_id": "4242", "company_name": "Hulek IT",
                                   "user": {"id": "124233", "name": "Jan Kowalski"}}},
        },
        "status": {"code": "OK"},
    }
    aioclient_mock.post(f"{BASE}/user_companies/find", json=payload)
    assert [c.id for c in await client(hass).list_companies()] == ["4242"]
