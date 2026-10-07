"""WebSocket API for the reports panel."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
import voluptuous as vol

from .const import DOMAIN, REPORT_DIR

REPORT_STEM = re.compile(
    r"ere_(?P<slug>[a-z0-9_]+)_(?P<year>\d{4})_q(?P<quarter>[1-4])"
)
REPORT_FILENAME = re.compile(REPORT_STEM.pattern + r"\.(?P<ext>xlsx|csv)")


@callback
def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_reports)


def _scan(folder: Path) -> dict[str, dict[str, Any]]:
    """Group the report files in the folder by stem."""
    found: dict[str, dict[str, Any]] = {}
    if not folder.is_dir():
        return found
    for path in folder.iterdir():
        if not (match := REPORT_FILENAME.fullmatch(path.name)):
            continue
        stem = path.name.rsplit(".", 1)[0]
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        item = found.setdefault(
            stem,
            {
                "stem": stem,
                "slug": match["slug"],
                "year": int(match["year"]),
                "quarter": int(match["quarter"]),
                "modified": modified,
                "files": [],
            },
        )
        item["files"].append(match["ext"])
        item["modified"] = max(item["modified"], modified)
    return found


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/reports"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_reports(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List charge points and the report files on disk."""
    found = await hass.async_add_executor_job(_scan, Path(hass.config.path(REPORT_DIR)))
    chargers = []
    known: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        manager = entry.runtime_data
        chargers.append({"entry_id": entry.entry_id, "title": entry.title})
        for stem, report in manager.reports.items():
            known[stem] = (entry.entry_id, entry.title, report)

    reports = []
    for stem, item in found.items():
        entry_id, title, meta = known.get(stem, (None, item["slug"], {}))
        reports.append(
            {
                "stem": stem,
                "entry_id": entry_id,
                "charger": title,
                "year": item["year"],
                "quarter": item["quarter"],
                "generated": meta.get("generated", item["modified"].isoformat()),
                "total_kwh": meta.get("total_kwh"),
                "sessions": meta.get("sessions"),
                "complete": meta.get("complete"),
                "files": sorted(item["files"], reverse=True),
            }
        )
    reports.sort(key=lambda r: (r["year"], r["quarter"], r["charger"]), reverse=True)
    connection.send_result(msg["id"], {"chargers": chargers, "reports": reports})
