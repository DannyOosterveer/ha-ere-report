"""ERE charging report: quarterly EV charging reports for the Dutch ERE scheme."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web
from homeassistant.components import panel_custom
from homeassistant.components.http import (
    KEY_HASS_USER,
    HomeAssistantView,
    StaticPathConfig,
)
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_QUARTER,
    ATTR_YEAR,
    DOMAIN,
    PANEL_URL,
    PLATFORMS,
    REPORT_DIR,
    SERVICE_GENERATE_REPORT,
    STATIC_URL,
)
from .history import previous_quarter
from .manager import EreReportManager
from .websocket import REPORT_FILENAME, async_register as async_register_websocket

type EreReportConfigEntry = ConfigEntry[EreReportManager]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_YEAR): vol.All(
            vol.Coerce(int), vol.Range(min=2000, max=2100)
        ),
        vol.Optional(ATTR_QUARTER): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
    }
)


class ReportDownloadView(HomeAssistantView):
    """Serve generated reports to administrators.

    The files hold the applicant's address and EAN code. Links in
    notifications are signed by the system content user when a report is
    created automatically, so system users are allowed as well.
    """

    url = f"/api/{DOMAIN}/{{filename}}"
    name = f"api:{DOMAIN}:download"

    async def get(self, request: web.Request, filename: str) -> web.StreamResponse:
        hass: HomeAssistant = request.app["hass"]
        user = request[KEY_HASS_USER]
        if not (user.is_admin or user.system_generated):
            raise web.HTTPForbidden
        if not REPORT_FILENAME.fullmatch(filename):
            raise web.HTTPNotFound
        path = Path(hass.config.path(REPORT_DIR, filename))
        if not await hass.async_add_executor_job(path.is_file):
            raise web.HTTPNotFound
        return web.FileResponse(
            path,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the download view, the reports panel and the report action."""
    hass.http.register_view(ReportDownloadView())
    async_register_websocket(hass)
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                STATIC_URL, str(Path(__file__).parent / "frontend"), cache_headers=False
            )
        ]
    )
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name="ere-report-panel",
        sidebar_title=(
            "ERE-rapporten" if hass.config.language.startswith("nl") else "ERE reports"
        ),
        sidebar_icon="mdi:file-chart-outline",
        module_url=f"{STATIC_URL}/ere-report-panel.js?v={integration.version}",
        require_admin=True,
    )

    async def generate_report(call: ServiceCall) -> ServiceResponse:
        entries: list[EreReportConfigEntry] = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]
        if entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID):
            entries = [entry for entry in entries if entry.entry_id == entry_id]
        if len(entries) != 1:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_found" if not entries else "entry_ambiguous",
            )
        year, quarter = previous_quarter(dt_util.now().date())
        year = call.data.get(ATTR_YEAR, year)
        quarter = call.data.get(ATTR_QUARTER, quarter)
        return await entries[0].runtime_data.async_generate(year, quarter)

    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_REPORT,
        generate_report,
        schema=SERVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EreReportConfigEntry) -> bool:
    """Set up a charge point."""
    manager = EreReportManager(hass, entry)
    await manager.async_start()
    entry.runtime_data = manager
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EreReportConfigEntry) -> bool:
    """Unload a charge point."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: EreReportConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
