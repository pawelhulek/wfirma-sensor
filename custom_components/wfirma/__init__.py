"""The wFirma integration: invoices, bills, revenue and tax deadlines from wfirma.pl."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import WfirmaClient
from .const import CONF_ACCESS_KEY, CONF_APP_KEY, CONF_COMPANY_ID, CONF_SECRET_KEY, DOMAIN
from .coordinator import WfirmaConfigEntry, WfirmaCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [Platform.CALENDAR, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions once, whatever the number of companies."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: WfirmaConfigEntry) -> bool:
    """Set up one wFirma company."""
    client = WfirmaClient(
        async_get_clientsession(hass),
        entry.data[CONF_ACCESS_KEY],
        entry.data[CONF_SECRET_KEY],
        entry.data[CONF_APP_KEY],
        entry.data.get(CONF_COMPANY_ID),
    )
    coordinator = WfirmaCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WfirmaConfigEntry) -> bool:
    """Unload a company."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
