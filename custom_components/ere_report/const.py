"""Constants for the ERE charging report integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "ere_report"
PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]

CONF_ENERGY_ENTITY = "energy_entity"
CONF_HOLDER_NAME = "holder_name"
CONF_ADDRESS = "address"
CONF_POSTCODE_CITY = "postcode_city"
CONF_EAN = "ean"
CONF_CHARGER_BRAND = "charger_brand"
CONF_CHARGER_MODEL = "charger_model"
CONF_CHARGER_SERIAL = "charger_serial"
CONF_IDLE_MINUTES = "idle_minutes"
CONF_MIN_SESSION_KWH = "min_session_kwh"
CONF_REPORT_LANGUAGE = "report_language"

DEFAULT_IDLE_MINUTES = 15
DEFAULT_MIN_SESSION_KWH = 0.05

STORAGE_VERSION = 1
REPORT_DIR = "ere_reports"

SERVICE_GENERATE_REPORT = "generate_report"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_YEAR = "year"
ATTR_QUARTER = "quarter"

EVENT_REPORT_GENERATED = f"{DOMAIN}_generated"
SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"
