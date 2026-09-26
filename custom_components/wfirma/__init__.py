"""The wFirma integration: invoices and revenue from wfirma.pl."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WfirmaClient
from .const import CONF_ACCESS_KEY, CONF_APP_KEY, CONF_COMPANY_ID, CONF_SECRET_KEY
from .coordinator import WfirmaConfigEntry, WfirmaCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


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
