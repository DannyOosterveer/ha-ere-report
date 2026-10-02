"""Tests for the config and options flow."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ere_report.config_flow import CONF_SHOW_ALL
from custom_components.ere_report.const import (
    CONF_EAN,
    CONF_ENERGY_ENTITY,
    CONF_HOLDER_NAME,
    CONF_IDLE_MINUTES,
    CONF_MID_CONFIRMED,
    CONF_MIN_SESSION_KWH,
    DOMAIN,
)

ENTITY = "sensor.charger_meter"


async def test_user_flow(recorder_mock, hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Laadpaal", CONF_ENERGY_ENTITY: ENTITY}
    )
    assert result["step_id"] == "details"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EAN: "12345", CONF_MID_CONFIRMED: True}
    )
    assert result["errors"] == {CONF_EAN: "invalid_ean"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOLDER_NAME: " J. Jansen ",
            CONF_EAN: "8712 3456 7890 1234 56",
            CONF_MID_CONFIRMED: True,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Laadpaal"
    assert result["data"] == {CONF_ENERGY_ENTITY: ENTITY}
    assert result["options"][CONF_EAN] == "871234567890123456"
    assert result["options"][CONF_HOLDER_NAME] == "J. Jansen"


async def test_same_sensor_twice_aborts(recorder_mock, hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN, unique_id=ENTITY, data={CONF_ENERGY_ENTITY: ENTITY}
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Nog een", CONF_ENERGY_ENTITY: ENTITY}
    )
    assert result["type"] is FlowResultType.ABORT


async def test_options_flow(recorder_mock, hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Laadpaal",
        unique_id=ENTITY,
        data={CONF_ENERGY_ENTITY: ENTITY},
        options={CONF_HOLDER_NAME: "J. Jansen"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_HOLDER_NAME: "J. Jansen",
            CONF_MID_CONFIRMED: True,
            CONF_IDLE_MINUTES: 30,
            CONF_MIN_SESSION_KWH: 0.1,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_IDLE_MINUTES] == 30
    assert entry.runtime_data.tracker.idle_timeout.total_seconds() == 1800


async def test_charger_meters_are_shortlisted(
    recorder_mock, hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    attrs = {
        "device_class": "energy",
        "state_class": "total_increasing",
        "unit_of_measurement": "kWh",
    }
    alfen = entity_registry.async_get_or_create(
        "sensor", "alfen_wallbox", "meter", suggested_object_id="ace_meter_reading"
    )
    hass.states.async_set(alfen.entity_id, "100", attrs)
    hass.states.async_set(
        "sensor.wallbox_energy", "5", {**attrs, "unit_of_measurement": "Wh"}
    )
    hass.states.async_set("sensor.p1_energy_import", "900", attrs)
    hass.states.async_set(
        "sensor.laadpaal_power", "3", {**attrs, "state_class": "measurement"}
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    entity_selector = result["data_schema"].schema[CONF_ENERGY_ENTITY]
    assert entity_selector.config["include_entities"] == [
        "sensor.ace_meter_reading",
        "sensor.wallbox_energy",
    ]
    assert CONF_SHOW_ALL in {str(key) for key in result["data_schema"].schema}

    # Asking for every energy sensor shows the form again with the wide filter.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Laadpaal", CONF_SHOW_ALL: True}
    )
    assert result["type"] is FlowResultType.FORM
    entity_selector = result["data_schema"].schema[CONF_ENERGY_ENTITY]
    assert entity_selector.config["device_class"] == ["energy"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Laadpaal", CONF_SHOW_ALL: True}
    )
    assert result["errors"] == {CONF_ENERGY_ENTITY: "select_entity"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Laadpaal", CONF_ENERGY_ENTITY: "sensor.p1_energy_import"},
    )
    assert result["step_id"] == "details"


async def test_without_candidates_all_energy_sensors_are_offered(
    recorder_mock, hass: HomeAssistant
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    schema = result["data_schema"].schema
    assert schema[CONF_ENERGY_ENTITY].config["device_class"] == ["energy"]
    assert CONF_SHOW_ALL not in {str(key) for key in schema}
