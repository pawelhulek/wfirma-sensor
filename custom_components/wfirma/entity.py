"""What every wFirma entity shares: one service device per company."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN


def device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, str(entry.unique_id))},
        name=entry.title,
        manufacturer="wFirma",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://wfirma.pl",
    )
