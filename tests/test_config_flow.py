"""Setting up wFirma from the UI, and re-entering keys."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wfirma.const import (
    CONF_ACCESS_KEY,
    CONF_APP_KEY,
    CONF_COMPANY_ID,
    CONF_COMPANY_NAME,
    CONF_SECRET_KEY,
    DOMAIN,
)
from custom_components.wfirma.exceptions import (
    WfirmaAuthError,
    WfirmaConnectionError,
    WfirmaRateLimitError,
    WfirmaResponseError,
)
from custom_components.wfirma.models import Company

KEYS = {CONF_ACCESS_KEY: "acc", CONF_SECRET_KEY: "sec", CONF_APP_KEY: "app"}
CLIENT = "custom_components.wfirma.config_flow.WfirmaClient"


@pytest.fixture(autouse=True)
def no_setup():
    with patch("custom_components.wfirma.async_setup_entry", return_value=True) as mock:
        yield mock


async def start(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def test_single_company_creates_entry(hass: HomeAssistant) -> None:
    result = await start(hass)
    with patch(f"{CLIENT}.list_companies", AsyncMock(return_value=(Company("4242", "Hulek IT"),))), patch(
        f"{CLIENT}.verify", AsyncMock()
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], KEYS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hulek IT"
    assert result["data"] == {**KEYS, CONF_COMPANY_ID: "4242", CONF_COMPANY_NAME: "Hulek IT"}
    assert result["result"].unique_id == "4242"


async def test_several_companies_ask_which_one(hass: HomeAssistant) -> None:
    result = await start(hass)
    companies = (Company("1", "First"), Company("2", "Second"))
    with patch(f"{CLIENT}.list_companies", AsyncMock(return_value=companies)), patch(f"{CLIENT}.verify", AsyncMock()):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], KEYS)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "company"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_COMPANY_ID: "2"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Second"
    assert result["data"][CONF_COMPANY_ID] == "2"


async def test_account_without_company_list_uses_default_company(hass: HomeAssistant) -> None:
    result = await start(hass)
    with patch(f"{CLIENT}.list_companies", AsyncMock(side_effect=WfirmaResponseError("ACTION NOT FOUND"))), patch(
        f"{CLIENT}.verify", AsyncMock()
    ) as verify:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], KEYS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "wFirma"
    assert result["data"][CONF_COMPANY_ID] is None
    assert verify.await_count == 1
    assert result["result"].unique_id and "acc" not in result["result"].unique_id


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (WfirmaAuthError("AUTH"), "invalid_auth"),
        (WfirmaRateLimitError("TOTAL REQUESTS LIMIT EXCEEDED"), "rate_limited"),
        (WfirmaConnectionError("down"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_errors_are_shown_and_recoverable(hass: HomeAssistant, error: Exception, code: str) -> None:
    result = await start(hass)
    with patch(f"{CLIENT}.list_companies", AsyncMock(side_effect=error)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], KEYS)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": code}
    with patch(f"{CLIENT}.list_companies", AsyncMock(return_value=(Company("4242", "Hulek IT"),))), patch(
        f"{CLIENT}.verify", AsyncMock()
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], KEYS)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_error_when_the_chosen_company_is_not_accessible(hass: HomeAssistant) -> None:
    result = await start(hass)
    companies = (Company("1", "First"), Company("2", "Second"))
    with patch(f"{CLIENT}.list_companies", AsyncMock(return_value=companies)), patch(
        f"{CLIENT}.verify", AsyncMock(side_effect=WfirmaAuthError("ACCESS DENIED"))
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], KEYS)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_COMPANY_ID: "2"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "company"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_same_company_twice_is_rejected(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="4242", data={**KEYS, CONF_COMPANY_ID: "4242"}).add_to_hass(hass)
    result = await start(hass)
    with patch(f"{CLIENT}.list_companies", AsyncMock(return_value=(Company("4242", "Hulek IT"),))), patch(
        f"{CLIENT}.verify", AsyncMock()
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], KEYS)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_keys(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="4242",
        data={**KEYS, CONF_COMPANY_ID: "4242", CONF_COMPANY_NAME: "Hulek IT"},
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    new_keys = {CONF_ACCESS_KEY: "acc2", CONF_SECRET_KEY: "sec2", CONF_APP_KEY: "app"}
    with patch(f"{CLIENT}.verify", AsyncMock()):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], new_keys)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_ACCESS_KEY] == "acc2"
    assert entry.data[CONF_COMPANY_ID] == "4242"


async def test_reauth_with_wrong_keys_shows_error(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="4242", data={**KEYS, CONF_COMPANY_ID: "4242"})
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    with patch(f"{CLIENT}.verify", AsyncMock(side_effect=WfirmaAuthError("AUTH"))):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], KEYS)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
