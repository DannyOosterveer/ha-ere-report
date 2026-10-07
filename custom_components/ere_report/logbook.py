"""Describe report events in the logbook."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_REPORT_GENERATED


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Show a generated report as a line in the logbook."""

    @callback
    def describe(event: Event) -> dict[str, Any]:
        data = event.data
        period = f"Q{data['quarter']} {data['year']}"
        kwh = f"{data['total_kwh']:.2f}"
        if hass.config.language.startswith("nl"):
            message = (
                f"heeft het rapport {period} gemaakt: {kwh.replace('.', ',')} kWh, "
                f"{data['sessions']} sessies"
            )
        else:
            message = (
                f"created the {period} report: {kwh} kWh, {data['sessions']} sessions"
            )
        entry: dict[str, Any] = {
            LOGBOOK_ENTRY_NAME: data["charger"],
            LOGBOOK_ENTRY_MESSAGE: message,
        }
        if entity_id := data.get("entity_id"):
            entry[LOGBOOK_ENTRY_ENTITY_ID] = entity_id
        return entry

    async_describe_event(DOMAIN, EVENT_REPORT_GENERATED, describe)
