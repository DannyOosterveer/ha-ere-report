"""Button for the ERE charging report integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import EreReportConfigEntry
from .entity import EreReportEntity
from .history import previous_quarter


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EreReportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [GenerateReportButton(entry.runtime_data, "generate_previous_quarter")]
    )


class GenerateReportButton(EreReportEntity, ButtonEntity):
    """Generate the report for the previous quarter."""

    async def async_press(self) -> None:
        await self.manager.async_generate(*previous_quarter(dt_util.now().date()))
