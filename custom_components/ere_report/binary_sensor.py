"""Binary sensor for the ERE charging report integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EreReportConfigEntry
from .entity import EreReportEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EreReportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [SessionActiveBinarySensor(entry.runtime_data, "session_active")]
    )


class SessionActiveBinarySensor(EreReportEntity, BinarySensorEntity):
    """On while a charging session is being recorded."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    @property
    def is_on(self) -> bool:
        return self.manager.tracker.active
