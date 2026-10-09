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
CONF_REPORT_LANGUAGE = "report_language"
CONF_PUSH_TARGETS = "push_targets"

DEFAULT_IDLE_MINUTES = 15
# The automatic report is made at this local time on the first day of a quarter,
# so its push notification does not arrive in the middle of the night.
DAILY_CHECK_HOUR = 9

STORAGE_VERSION = 1
REPORT_DIR = "ere_reports"

SERVICE_GENERATE_REPORT = "generate_report"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_YEAR = "year"
ATTR_QUARTER = "quarter"

EVENT_REPORT_GENERATED = f"{DOMAIN}_generated"
PANEL_URL = "ere-report"
STATIC_URL = f"/{DOMAIN}_static"
SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"
