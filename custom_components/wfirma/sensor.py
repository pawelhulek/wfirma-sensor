"""wFirma sensors: sales invoices, cost invoices, revenue and the next tax deadlines."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BASE_CURRENCY
from .coordinator import Snapshot, WfirmaConfigEntry, WfirmaCoordinator
from .deadlines import DeadlineKind, TaxProfile, last_payment, next_deadline
from .entity import device_info

PARALLEL_UPDATES = 0  # the coordinator does the polling

type Value = int | Decimal | date | None


def _other_currencies(totals: Mapping[str, Decimal]) -> dict[str, Any]:
    """Amounts in other currencies are listed, never converted into PLN."""
    return {"other_currencies": {c: float(v) for c, v in sorted(totals.items())}} if totals else {}


@dataclass(frozen=True, kw_only=True)
class WfirmaSensorDescription(SensorEntityDescription):
    """How one sensor reads the snapshot."""

    value_fn: Callable[[Snapshot], Value]
    attrs_fn: Callable[[Snapshot], dict[str, Any]] = lambda _: {}
    available_fn: Callable[[Snapshot], bool] = lambda _: True
    applies_fn: Callable[[TaxProfile | None], bool] = lambda _: True


_COUNT: dict[str, Any] = {"state_class": SensorStateClass.MEASUREMENT}
_MONEY: dict[str, Any] = {
    "device_class": SensorDeviceClass.MONETARY,
    "native_unit_of_measurement": BASE_CURRENCY,
    "suggested_display_precision": 2,
}

INVOICE_SENSORS: tuple[WfirmaSensorDescription, ...] = (
    WfirmaSensorDescription(
        key="unpaid_invoices",
        translation_key="unpaid_invoices",
        value_fn=lambda d: d.invoices.unpaid_count,
        attrs_fn=lambda d: {"invoices": d.invoices.unpaid_attributes()},
        **_COUNT,
    ),
    WfirmaSensorDescription(
        key="unpaid_amount",
        translation_key="unpaid_amount",
        value_fn=lambda d: d.invoices.unpaid_amount,
        attrs_fn=lambda d: _other_currencies(d.invoices.unpaid_other_currencies),
        **_MONEY,
    ),
    WfirmaSensorDescription(
        key="overdue_invoices",
        translation_key="overdue_invoices",
        value_fn=lambda d: d.invoices.overdue_count,
        attrs_fn=lambda d: {"invoices": d.invoices.overdue_attributes()},
        **_COUNT,
    ),
    WfirmaSensorDescription(
        key="overdue_amount",
        translation_key="overdue_amount",
        value_fn=lambda d: d.invoices.overdue_amount,
        attrs_fn=lambda d: _other_currencies(d.invoices.overdue_other_currencies),
        **_MONEY,
    ),
    WfirmaSensorDescription(
        key="revenue_month_net",
        translation_key="revenue_month_net",
        value_fn=lambda d: d.invoices.revenue_net,
        attrs_fn=lambda d: {"documents": d.invoices.revenue_count},
        **_MONEY,
    ),
    WfirmaSensorDescription(
        key="revenue_month_gross",
        translation_key="revenue_month_gross",
        value_fn=lambda d: d.invoices.revenue_gross,
        attrs_fn=lambda d: {
            "documents": d.invoices.revenue_count,
            **_other_currencies(d.invoices.revenue_other_currencies),
        },
        **_MONEY,
    ),
)


def _expense_attrs(d: Snapshot) -> dict[str, Any]:
    e = d.expenses
    if e is None:
        return {}
    return {
        "expenses": e.unpaid_attributes(),
        "overdue": len(e.overdue),
        "next_due": e.next_due.isoformat() if e.next_due else None,
    }


EXPENSE_SENSORS: tuple[WfirmaSensorDescription, ...] = (
    WfirmaSensorDescription(
        key="unpaid_expenses",
        translation_key="unpaid_expenses",
        value_fn=lambda d: d.expenses.unpaid_count if d.expenses else None,
        attrs_fn=_expense_attrs,
        available_fn=lambda d: d.expenses is not None,
        **_COUNT,
    ),
    WfirmaSensorDescription(
        key="unpaid_expenses_amount",
        translation_key="unpaid_expenses_amount",
        value_fn=lambda d: d.expenses.unpaid_amount if d.expenses else None,
        attrs_fn=lambda d: _other_currencies(d.expenses.other_currencies) if d.expenses else {},
        available_fn=lambda d: d.expenses is not None,
        **_MONEY,
    ),
)


def _deadline_value(kind: DeadlineKind) -> Callable[[Snapshot], Value]:
    def value(d: Snapshot) -> Value:
        found = next_deadline(d.deadlines or (), kind, d.today)
        return found.due if found else None

    return value


def _deadline_attrs(kind: DeadlineKind) -> Callable[[Snapshot], dict[str, Any]]:
    def attrs(d: Snapshot) -> dict[str, Any]:
        found = next_deadline(d.deadlines or (), kind, d.today)
        result: dict[str, Any] = {}
        if found is not None:
            result = {
                "period": f"{found.period.year}-{found.period.month:02d}",
                "paid": found.paid,
                "overdue": found.is_overdue(d.today),
                "days_left": found.days_left(d.today),
            }
        last = last_payment(d.tax_payments or (), zus=kind is DeadlineKind.ZUS)
        if kind is DeadlineKind.ZUS:
            result["estimated_amount"] = float(last.amount) if last else None
        if kind is DeadlineKind.INCOME_TAX and d.profile is not None:
            result["tax_form"] = d.profile.income_tax
        result["last_payment_date"] = last.paid_on.isoformat() if last else None
        return result

    return attrs


def _deadline_sensor(kind: DeadlineKind, applies: Callable[[TaxProfile | None], bool]) -> WfirmaSensorDescription:
    return WfirmaSensorDescription(
        key=f"next_{kind.value}_payment",
        translation_key=f"next_{kind.value}_payment",
        device_class=SensorDeviceClass.DATE,
        value_fn=_deadline_value(kind),
        attrs_fn=_deadline_attrs(kind),
        available_fn=lambda d: d.deadlines is not None,
        applies_fn=applies,
    )


# A sensor is left out only when the tax settings are known and say it does not apply.
DEADLINE_SENSORS: tuple[WfirmaSensorDescription, ...] = (
    _deadline_sensor(DeadlineKind.ZUS, lambda _: True),
    _deadline_sensor(DeadlineKind.INCOME_TAX, lambda p: p is None or DeadlineKind.INCOME_TAX in p.kinds),
    _deadline_sensor(DeadlineKind.VAT, lambda p: p is None or p.vat_payer),
)

SENSORS: tuple[WfirmaSensorDescription, ...] = (*INVOICE_SENSORS, *EXPENSE_SENSORS, *DEADLINE_SENSORS)


async def async_setup_entry(
    hass: HomeAssistant, entry: WfirmaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Create the sensors for one company."""
    coordinator = entry.runtime_data
    profile = coordinator.data.profile if coordinator.data else None
    async_add_entities(WfirmaSensor(coordinator, d) for d in SENSORS if d.applies_fn(profile))


class WfirmaSensor(CoordinatorEntity[WfirmaCoordinator], SensorEntity):
    """A figure from the latest wFirma snapshot."""

    _attr_has_entity_name = True
    entity_description: WfirmaSensorDescription

    def __init__(self, coordinator: WfirmaCoordinator, description: WfirmaSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = device_info(entry)

    @property
    def available(self) -> bool:
        return super().available and self.entity_description.available_fn(self.coordinator.data)

    @property
    def native_value(self) -> Value:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attrs_fn(self.coordinator.data)
