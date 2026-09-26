"""wFirma sensors: unpaid, overdue and this month's revenue."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BASE_CURRENCY, DOMAIN
from .coordinator import WfirmaConfigEntry, WfirmaCoordinator
from .summary import Summary

PARALLEL_UPDATES = 0  # the coordinator does the polling


def _other_currencies(totals: Mapping[str, Decimal]) -> dict[str, Any]:
    """Amounts in other currencies are listed, never converted into PLN."""
    return {"other_currencies": {c: float(v) for c, v in sorted(totals.items())}} if totals else {}


@dataclass(frozen=True, kw_only=True)
class WfirmaSensorDescription(SensorEntityDescription):
    """How one sensor reads the summary."""

    value_fn: Callable[[Summary], int | Decimal]
    attrs_fn: Callable[[Summary], dict[str, Any]] = lambda _: {}


_COUNT: dict[str, Any] = {"state_class": SensorStateClass.MEASUREMENT}
_MONEY: dict[str, Any] = {
    "device_class": SensorDeviceClass.MONETARY,
    "native_unit_of_measurement": BASE_CURRENCY,
    "suggested_display_precision": 2,
}

SENSORS: tuple[WfirmaSensorDescription, ...] = (
    WfirmaSensorDescription(
        key="unpaid_invoices",
        translation_key="unpaid_invoices",
        value_fn=lambda s: s.unpaid_count,
        attrs_fn=lambda s: {"invoices": s.unpaid_attributes()},
        **_COUNT,
    ),
    WfirmaSensorDescription(
        key="unpaid_amount",
        translation_key="unpaid_amount",
        value_fn=lambda s: s.unpaid_amount,
        attrs_fn=lambda s: _other_currencies(s.unpaid_other_currencies),
        **_MONEY,
    ),
    WfirmaSensorDescription(
        key="overdue_invoices",
        translation_key="overdue_invoices",
        value_fn=lambda s: s.overdue_count,
        attrs_fn=lambda s: {"invoices": s.overdue_attributes()},
        **_COUNT,
    ),
    WfirmaSensorDescription(
        key="overdue_amount",
        translation_key="overdue_amount",
        value_fn=lambda s: s.overdue_amount,
        attrs_fn=lambda s: _other_currencies(s.overdue_other_currencies),
        **_MONEY,
    ),
    WfirmaSensorDescription(
        key="revenue_month_net",
        translation_key="revenue_month_net",
        value_fn=lambda s: s.revenue_net,
        attrs_fn=lambda s: {"documents": s.revenue_count},
        **_MONEY,
    ),
    WfirmaSensorDescription(
        key="revenue_month_gross",
        translation_key="revenue_month_gross",
        value_fn=lambda s: s.revenue_gross,
        attrs_fn=lambda s: {"documents": s.revenue_count, **_other_currencies(s.revenue_other_currencies)},
        **_MONEY,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: WfirmaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Create the sensors for one company."""
    async_add_entities(WfirmaSensor(entry.runtime_data, description) for description in SENSORS)


class WfirmaSensor(CoordinatorEntity[WfirmaCoordinator], SensorEntity):
    """A figure from the latest wFirma summary."""

    _attr_has_entity_name = True
    entity_description: WfirmaSensorDescription

    def __init__(self, coordinator: WfirmaCoordinator, description: WfirmaSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(entry.unique_id))},
            name=entry.title,
            manufacturer="wFirma",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://wfirma.pl",
        )

    @property
    def native_value(self) -> int | Decimal:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attrs_fn(self.coordinator.data)
