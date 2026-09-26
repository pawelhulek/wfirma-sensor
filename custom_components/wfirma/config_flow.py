"""Set up wFirma from the UI, and re-enter keys when they stop working."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import WfirmaClient
from .const import (
    CONF_ACCESS_KEY,
    CONF_APP_KEY,
    CONF_COMPANY_ID,
    CONF_COMPANY_NAME,
    CONF_SECRET_KEY,
    DOMAIN,
)
from .exceptions import (
    WfirmaAuthError,
    WfirmaConnectionError,
    WfirmaError,
    WfirmaRateLimitError,
    WfirmaResponseError,
)
from .models import Company

_LOGGER = logging.getLogger(__name__)
_KEY_FIELDS = (CONF_ACCESS_KEY, CONF_SECRET_KEY, CONF_APP_KEY)
_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
KEYS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ACCESS_KEY): str,
        vol.Required(CONF_SECRET_KEY): _PASSWORD,
        vol.Required(CONF_APP_KEY): _PASSWORD,
    }
)


def _error_code(err: Exception) -> str:
    """Map a failure to the message shown in the form."""
    if isinstance(err, WfirmaAuthError):
        return "invalid_auth"
    if isinstance(err, WfirmaRateLimitError):
        return "rate_limited"
    if isinstance(err, WfirmaConnectionError):
        return "cannot_connect"
    if not isinstance(err, WfirmaError):
        _LOGGER.exception("Unexpected error while talking to wFirma", exc_info=err)
    return "unknown"


def _keys(user_input: Mapping[str, Any]) -> dict[str, str]:
    return {field: str(user_input[field]).strip() for field in _KEY_FIELDS}


def _anonymous_id(access_key: str) -> str:
    """A stable id for accounts that do not list companies, without exposing the key."""
    return "key-" + hashlib.sha256(access_key.encode()).hexdigest()[:16]


class WfirmaConfigFlow(ConfigFlow, domain=DOMAIN):
    """One entry per wFirma company."""

    VERSION = 1

    def __init__(self) -> None:
        self._pending_keys: dict[str, str] = {}
        self._companies: tuple[Company, ...] = ()

    def _client(self, keys: Mapping[str, str], company_id: str | None = None) -> WfirmaClient:
        return WfirmaClient(
            async_get_clientsession(self.hass),
            keys[CONF_ACCESS_KEY],
            keys[CONF_SECRET_KEY],
            keys[CONF_APP_KEY],
            company_id,
        )

    async def _try_create(self, company: Company | None) -> tuple[ConfigFlowResult | None, str | None]:
        """Check the keys work for this company, then create the entry."""
        try:
            await self._client(self._pending_keys, company.id if company else None).verify()
        except Exception as err:  # noqa: BLE001 - every failure becomes a form error
            return None, _error_code(err)
        await self.async_set_unique_id(company.id if company else _anonymous_id(self._pending_keys[CONF_ACCESS_KEY]))
        self._abort_if_unique_id_configured()
        return (
            self.async_create_entry(
                title=company.name if company else "wFirma",
                data={
                    **self._pending_keys,
                    CONF_COMPANY_ID: company.id if company else None,
                    CONF_COMPANY_NAME: company.name if company else None,
                },
            ),
            None,
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            keys = _keys(user_input)
            try:
                companies = await self._list_companies(keys)
            except Exception as err:  # noqa: BLE001 - every failure becomes a form error
                errors["base"] = _error_code(err)
            else:
                self._pending_keys = keys
                if len(companies) > 1:
                    self._companies = companies
                    return await self.async_step_company()
                result, error = await self._try_create(companies[0] if companies else None)
                if result is not None:
                    return result
                errors["base"] = str(error)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                KEYS_SCHEMA, {CONF_ACCESS_KEY: (user_input or {}).get(CONF_ACCESS_KEY, "")}
            ),
            errors=errors,
        )

    async def _list_companies(self, keys: Mapping[str, str]) -> tuple[Company, ...]:
        """Companies these keys can see; accounts without that module list none."""
        try:
            return await self._client(keys).list_companies()
        except WfirmaResponseError:
            return ()

    async def async_step_company(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            chosen = next(c for c in self._companies if c.id == user_input[CONF_COMPANY_ID])
            result, error = await self._try_create(chosen)
            if result is not None:
                return result
            errors["base"] = str(error)
        options = [SelectOptionDict(value=c.id, label=c.name) for c in self._companies]
        return self.async_show_form(
            step_id="company",
            data_schema=vol.Schema({vol.Required(CONF_COMPANY_ID): SelectSelector(SelectSelectorConfig(options=options))}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            keys = _keys(user_input)
            try:
                await self._client(keys, entry.data.get(CONF_COMPANY_ID)).verify()
            except Exception as err:  # noqa: BLE001 - every failure becomes a form error
                errors["base"] = _error_code(err)
            else:
                return self.async_update_reload_and_abort(entry, data_updates=keys)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=KEYS_SCHEMA,
            errors=errors,
            description_placeholders={"company": entry.title},
        )
