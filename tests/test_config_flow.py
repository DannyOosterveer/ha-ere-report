"""Tests for the config and options flow."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ere_report.config_flow import CONF_SHOW_ALL
from custom_components.ere_report.const import (
    CONF_CHARGER_BRAND,
    CONF_CHARGER_MODEL,
    CONF_CHARGER_SERIAL,
    CONF_EAN,
    CONF_ENERGY_ENTITY,
    CONF_HOLDER_NAME,
    CONF_IDLE_MINUTES,
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
        result["flow_id"], {CONF_EAN: "12345"}
    )
    assert result["errors"] == {CONF_EAN: "invalid_ean"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOLDER_NAME: " J. Jansen ",
            CONF_EAN: "8712 3456 7890 1234 56",
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
            CONF_IDLE_MINUTES: 30,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_IDLE_MINUTES] == 30
    assert entry.options["auto_report"] is True
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


async def test_details_are_prefilled_from_the_charger(
    recorder_mock,
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    other = MockConfigEntry(domain="alfen_wallbox")
    other.add_to_hass(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={("alfen_wallbox", "box")},
        manufacturer="Alfen",
        model="Eve Single Pro-line",
        serial_number="ACE0001",
    )
    meter = entity_registry.async_get_or_create(
        "sensor",
        "alfen_wallbox",
        "meter",
        device_id=device.id,
        suggested_object_id="ace_meter_reading",
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Laadpaal", CONF_ENERGY_ENTITY: meter.entity_id}
    )
    suggested = {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }
    assert suggested[CONF_CHARGER_BRAND] == "Alfen"
    assert suggested[CONF_CHARGER_MODEL] == "Eve Single Pro-line"
    assert suggested[CONF_CHARGER_SERIAL] == "ACE0001"
    assert suggested[CONF_EAN] == ""

    # Everything is optional: submitting the form as it is creates the entry.
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_EAN] == ""


async def test_push_targets_list_admin_phones(
    recorder_mock, hass: HomeAssistant, hass_admin_user, hass_read_only_user
) -> None:
    from .test_init import add_phone

    add_phone(hass, "Admin Phone", hass_admin_user.id)
    add_phone(hass, "Other Phone", hass_read_only_user.id)
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
    key = next(k for k in result["data_schema"].schema if str(k) == "push_targets")
    options = result["data_schema"].schema[key].config["options"]
    assert [o["value"] for o in options] == ["mobile_app_admin_phone"]
    assert key.default() == ["mobile_app_admin_phone"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_HOLDER_NAME: "J. Jansen", "push_targets": []}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["push_targets"] == []
