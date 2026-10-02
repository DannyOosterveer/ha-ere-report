"""Base entity for the ERE charging report integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import CONF_CHARGER_BRAND, CONF_CHARGER_MODEL, DOMAIN
from .manager import EreReportManager


class EreReportEntity(Entity):
    """Entity that refreshes whenever the manager has news."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: EreReportManager, key: str) -> None:
        self.manager = manager
        entry = manager.entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=entry.options.get(CONF_CHARGER_BRAND) or None,
            model=entry.options.get(CONF_CHARGER_MODEL) or None,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self.manager.signal, self.async_write_ha_state
            )
        )
