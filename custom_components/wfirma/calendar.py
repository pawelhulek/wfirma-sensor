"""A calendar of tax deadlines and payment dates for one wFirma company."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .agenda import AgendaItem, agenda
from .coordinator import WfirmaConfigEntry, WfirmaCoordinator
from .entity import device_info

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: WfirmaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([WfirmaCalendar(entry.runtime_data)])


def _event(item: AgendaItem) -> CalendarEvent:
    return CalendarEvent(
        start=item.day,
        end=item.day + timedelta(days=1),
        summary=item.summary,
        description=item.description,
        uid=item.uid,
    )


class WfirmaCalendar(CoordinatorEntity[WfirmaCoordinator], CalendarEntity):
    """All-day events built from the latest poll; reading it never calls wFirma."""

    _attr_has_entity_name = True
    _attr_translation_key = "calendar"

    def __init__(self, coordinator: WfirmaCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id}_calendar"
        self._attr_device_info = device_info(entry)

    def _items(self) -> tuple[AgendaItem, ...]:
        return agenda(self.coordinator.data, self.hass.config.language)

    @property
    def event(self) -> CalendarEvent | None:
        """The current or next item."""
        today = dt_util.now().date()
        upcoming = next((i for i in self._items() if i.day >= today), None)
        return _event(upcoming) if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """All-day items overlapping [start_date, end_date)."""
        return [_event(i) for i in self._items() if _overlaps(i, start_date, end_date)]


def _overlaps(item: AgendaItem, start: datetime, end: datetime) -> bool:
    day_start = dt_util.start_of_local_day(item.day)
    return day_start < end and day_start + timedelta(days=1) > start
