"""Config flow for the ERE charging report integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    ATTR_STATE_CLASS,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_UNIT_OF_MEASUREMENT, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, selector
import voluptuous as vol

from .const import (
    CONF_ADDRESS,
    CONF_CHARGER_BRAND,
    CONF_CHARGER_MODEL,
    CONF_CHARGER_SERIAL,
    CONF_EAN,
    CONF_ENERGY_ENTITY,
    CONF_HOLDER_NAME,
    CONF_IDLE_MINUTES,
    CONF_MID_CONFIRMED,
    CONF_MIN_SESSION_KWH,
    CONF_POSTCODE_CITY,
    CONF_REPORT_LANGUAGE,
    DEFAULT_IDLE_MINUTES,
    DEFAULT_MIN_SESSION_KWH,
    DOMAIN,
)
from .report_text import DEFAULT_LANGUAGE, LANGUAGES

TEXT_FIELDS = (
    CONF_HOLDER_NAME,
    CONF_ADDRESS,
    CONF_POSTCODE_CITY,
    CONF_EAN,
    CONF_CHARGER_BRAND,
    CONF_CHARGER_MODEL,
    CONF_CHARGER_SERIAL,
)

# Integrations that expose an EV charger's own kWh meter.
CHARGER_PLATFORMS = {
    "alfen_wallbox",
    "charge_amps",
    "easee",
    "evcc",
    "goecharger",
    "go_echarger",
    "keba",
    "myenergi",
    "ocpp",
    "openevse",
    "peblar",
    "smartevse",
    "tesla_wall_connector",
    "wallbox",
    "webasto",
    "zaptec",
}
CHARGER_KEYWORDS = (
    "laadpaal",
    "laadpunt",
    "laadstation",
    "charger",
    "charge_point",
    "chargepoint",
    "charging",
    "wallbox",
    "evse",
    "zappi",
    "socket",
)
ENERGY_UNITS = {"Wh", "kWh", "MWh"}
CONF_SHOW_ALL = "show_all"


def _charger_meter_candidates(hass: HomeAssistant) -> list[str]:
    """Cumulative energy sensors that look like an EV charger's meter."""
    registry = er.async_get(hass)
    candidates = []
    for state in hass.states.async_all("sensor"):
        attrs = state.attributes
        if (
            attrs.get(ATTR_DEVICE_CLASS) != SensorDeviceClass.ENERGY
            or attrs.get(ATTR_STATE_CLASS) != SensorStateClass.TOTAL_INCREASING
            or attrs.get(ATTR_UNIT_OF_MEASUREMENT) not in ENERGY_UNITS
        ):
            continue
        entry = registry.async_get(state.entity_id)
        haystack = f"{state.entity_id} {state.name}".lower()
        if (entry and entry.platform in CHARGER_PLATFORMS) or any(
            keyword in haystack for keyword in CHARGER_KEYWORDS
        ):
            candidates.append(state.entity_id)
    return sorted(candidates)


def _user_schema(candidates: list[str], show_all: bool) -> vol.Schema:
    if candidates and not show_all:
        config = selector.EntitySelectorConfig(include_entities=candidates)
    else:
        config = selector.EntitySelectorConfig(domain="sensor", device_class="energy")
    schema: dict[Any, Any] = {
        vol.Required(CONF_NAME): selector.TextSelector(),
        vol.Optional(CONF_ENERGY_ENTITY): selector.EntitySelector(config),
    }
    if candidates:
        schema[vol.Optional(CONF_SHOW_ALL, default=show_all)] = (
            selector.BooleanSelector()
        )
    return vol.Schema(schema)


def _details_schema(defaults: dict[str, Any], with_tuning: bool) -> vol.Schema:
    schema: dict[Any, Any] = {
        vol.Optional(
            field, description={"suggested_value": defaults.get(field, "")}
        ): selector.TextSelector()
        for field in TEXT_FIELDS
    }
    schema[
        vol.Required(
            CONF_MID_CONFIRMED, default=defaults.get(CONF_MID_CONFIRMED, False)
        )
    ] = selector.BooleanSelector()
    schema[
        vol.Required(
            CONF_REPORT_LANGUAGE,
            default=defaults.get(CONF_REPORT_LANGUAGE, DEFAULT_LANGUAGE),
        )
    ] = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(LANGUAGES),
            translation_key=CONF_REPORT_LANGUAGE,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )
    if with_tuning:
        schema[
            vol.Required(
                CONF_IDLE_MINUTES,
                default=defaults.get(CONF_IDLE_MINUTES, DEFAULT_IDLE_MINUTES),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=240,
                step=1,
                unit_of_measurement="min",
                mode=selector.NumberSelectorMode.BOX,
            )
        )
        schema[
            vol.Required(
                CONF_MIN_SESSION_KWH,
                default=defaults.get(CONF_MIN_SESSION_KWH, DEFAULT_MIN_SESSION_KWH),
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=5,
                step=0.01,
                unit_of_measurement="kWh",
                mode=selector.NumberSelectorMode.BOX,
            )
        )
    return vol.Schema(schema)


def _clean(user_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Normalise the details and validate the EAN (18 digits, optional)."""
    data = dict(user_input)
    for field in TEXT_FIELDS:
        data[field] = str(data.get(field, "")).strip()
    data[CONF_EAN] = data[CONF_EAN].replace(" ", "")
    errors = {}
    if data[CONF_EAN] and not (data[CONF_EAN].isdigit() and len(data[CONF_EAN]) == 18):
        errors[CONF_EAN] = "invalid_ean"
    return data, errors


class EreReportConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a charge point: pick the meter, then enter the report details."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._shown_all = False

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EreReportOptionsFlow:
        return EreReportOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        candidates = _charger_meter_candidates(self.hass)
        show_all = bool(user_input and user_input.get(CONF_SHOW_ALL))
        if user_input is not None:
            if show_all and not self._shown_all:
                # Switch from the shortlist to every energy sensor.
                self._shown_all = True
            elif not user_input.get(CONF_ENERGY_ENTITY):
                errors[CONF_ENERGY_ENTITY] = "select_entity"
            else:
                await self.async_set_unique_id(user_input[CONF_ENERGY_ENTITY])
                self._abort_if_unique_id_configured()
                self._data = user_input
                return await self.async_step_details()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _user_schema(candidates, show_all=show_all), user_input
            ),
            errors=errors,
            description_placeholders={"candidates": str(len(candidates))},
        )

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            options, errors = _clean(user_input)
            if not errors:
                return self.async_create_entry(
                    title=self._data[CONF_NAME],
                    data={CONF_ENERGY_ENTITY: self._data[CONF_ENERGY_ENTITY]},
                    options=options,
                )
        return self.async_show_form(
            step_id="details",
            data_schema=_details_schema(user_input or {}, with_tuning=False),
            errors=errors,
        )


class EreReportOptionsFlow(OptionsFlow):
    """Edit the report details and session detection settings."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            options, errors = _clean(user_input)
            if not errors:
                return self.async_create_entry(data=options)
        return self.async_show_form(
            step_id="init",
            data_schema=_details_schema(
                user_input or dict(self.config_entry.options), with_tuning=True
            ),
            errors=errors,
        )
