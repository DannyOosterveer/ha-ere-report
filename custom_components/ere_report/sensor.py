"""Sensors for the ERE charging report integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EreReportConfigEntry
from .entity import EreReportEntity
from .manager import EreReportManager


@dataclass(frozen=True, kw_only=True)
class EreReportSensorDescription(SensorEntityDescription):
    value_fn: Callable[[EreReportManager], float | int | None]
    attributes_fn: Callable[[EreReportManager], dict[str, Any] | None] = lambda _: None


def _last_session_attributes(manager: EreReportManager) -> dict[str, Any] | None:
    if (session := manager.last_session) is None:
        return None
    return {
        "start": session.start.isoformat(),
        "end": session.end.isoformat(),
        "meter_start": session.meter_start,
        "meter_end": session.meter_end,
        "source": session.source,
    }


SENSORS = (
    EreReportSensorDescription(
        key="quarter_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda manager: manager.quarter_energy,
    ),
    EreReportSensorDescription(
        key="quarter_sessions",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda manager: manager.sessions_this_quarter,
    ),
    EreReportSensorDescription(
        key="last_session_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda manager: (
            manager.last_session.kwh if manager.last_session else None
        ),
        attributes_fn=_last_session_attributes,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EreReportConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        EreReportSensor(entry.runtime_data, description) for description in SENSORS
    )


class EreReportSensor(EreReportEntity, SensorEntity):
    """Sensor backed by the session manager."""

    entity_description: EreReportSensorDescription

    def __init__(
        self, manager: EreReportManager, description: EreReportSensorDescription
    ) -> None:
        super().__init__(manager, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | None:
        return self.entity_description.value_fn(self.manager)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.entity_description.attributes_fn(self.manager)
