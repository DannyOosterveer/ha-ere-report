"""Tests for the feedback around a report: button, logbook, sensor and panel."""

from pathlib import Path
from unittest.mock import patch

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)
from pytest_homeassistant_custom_component.typing import (
    ClientSessionGenerator,
    WebSocketGenerator,
)

from custom_components.ere_report.const import DOMAIN, PANEL_URL, STATIC_URL
from custom_components.ere_report.history import previous_quarter

from .test_init import ATTRS, ENTITY, setup_entry

BUTTON = "button.laadpaal_generate_report_for_previous_quarter"
LAST_REPORT = "sensor.laadpaal_last_report"


@pytest.fixture
def report_files(hass: HomeAssistant):
    """Remove report files written during a test."""
    yield
    folder = Path(hass.config.path("ere_reports"))
    for path in folder.glob("ere_laadpaal_*"):
        path.unlink()


async def test_button_press_shows_result(
    recorder_mock,
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    report_files,
) -> None:
    assert await async_setup_component(hass, "logbook", {})
    hass.states.async_set(ENTITY, "1000.0", ATTRS)
    entry = await setup_entry(hass)
    assert hass.states.get(LAST_REPORT).state == "unknown"

    await hass.services.async_call(
        "button", "press", {"entity_id": BUTTON}, blocking=True
    )
    await hass.async_block_till_done()

    year, quarter = previous_quarter(dt_util.now().date())
    state = hass.states.get(LAST_REPORT)
    assert state.state != "unknown"
    assert state.attributes["period"] == f"Q{quarter} {year}"
    assert entry.runtime_data.last_report["quarter"] == quarter

    # The logbook shows the outcome, linked to the button press.
    await async_wait_recording_done(hass)
    client = await hass_client()
    response = await client.get(f"/api/logbook?entity={LAST_REPORT}")
    entries = await response.json()
    [line] = [e for e in entries if "message" in e and "report" in e["message"]]
    assert line["name"] == "Laadpaal"
    assert line["message"].startswith(f"created the Q{quarter} {year} report")
    assert line["entity_id"] == LAST_REPORT
    assert (line["context_domain"], line["context_service"]) == ("button", "press")


async def test_failure_is_shown(
    recorder_mock, hass: HomeAssistant, report_files
) -> None:
    hass.states.async_set(ENTITY, "1000.0", ATTRS)
    entry = await setup_entry(hass)
    with (
        patch(
            "custom_components.ere_report.manager.write_xlsx",
            side_effect=PermissionError("read-only file system"),
        ),
        pytest.raises(HomeAssistantError, match="read-only file system"),
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": BUTTON}, blocking=True
        )
    assert entry.runtime_data.last_report is None

    # The automatic report notifies instead of failing silently.
    manager = entry.runtime_data
    manager._last_auto_report = "2000Q1"
    with patch(
        "custom_components.ere_report.manager.write_xlsx",
        side_effect=PermissionError("read-only file system"),
    ):
        await manager._handle_daily(dt_util.utcnow())
    notifications = persistent_notification._async_get_or_create_notifications(hass)
    [failure] = [n for n in notifications.values() if "failed" in n["title"]]
    assert "read-only file system" in failure["message"]
    assert manager._last_auto_report == "2000Q1"


async def test_panel_lists_and_serves_reports(
    recorder_mock,
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user,
    report_files,
) -> None:
    hass.states.async_set(ENTITY, "1000.0", ATTRS)
    entry = await setup_entry(hass)
    assert PANEL_URL in hass.data["frontend_panels"]
    client = await hass_client()
    script = await client.get(f"{STATIC_URL}/ere-report-panel.js")
    assert script.status == 200
    assert "ere-report-panel" in await script.text()

    year, quarter = previous_quarter(dt_util.now().date())
    await entry.runtime_data.async_generate(year, quarter)

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": f"{DOMAIN}/reports"})
    result = (await ws.receive_json())["result"]
    assert result["chargers"] == [{"entry_id": entry.entry_id, "title": "Laadpaal"}]
    [report] = result["reports"]
    assert report["entry_id"] == entry.entry_id
    assert (report["year"], report["quarter"]) == (year, quarter)
    assert report["files"] == ["xlsx", "csv"]
    assert report["sessions"] == 0

    # A signed link from the panel downloads the file.
    await ws.send_json(
        {
            "id": 2,
            "type": "auth/sign_path",
            "path": f"/api/{DOMAIN}/{report['stem']}.xlsx",
        }
    )
    signed = (await ws.receive_json())["result"]["path"]
    download = await client.get(signed)
    assert download.status == 200

    # Non-admins get neither the list nor the files.
    hass_admin_user.groups = []
    await ws.send_json({"id": 3, "type": f"{DOMAIN}/reports"})
    assert (await ws.receive_json())["error"]["code"] == "unauthorized"
    forbidden = await client.get(f"/api/{DOMAIN}/{report['stem']}.csv")
    assert forbidden.status == 403


async def test_panel_fills_in_reports_from_older_versions(
    recorder_mock,
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    report_files,
) -> None:
    """Reports made before 0.2.0 have no record; the list reads the file."""
    hass.states.async_set(ENTITY, "1000.0", ATTRS)
    entry = await setup_entry(hass)
    year, quarter = previous_quarter(dt_util.now().date())
    result = await entry.runtime_data.async_generate(year, quarter)
    entry.runtime_data.reports.clear()

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": f"{DOMAIN}/reports"})
    [report] = (await ws.receive_json())["result"]["reports"]
    assert report["charger"] == "Laadpaal"
    assert report["entry_id"] == entry.entry_id
    assert report["total_kwh"] == result["total_kwh"]
    assert report["sessions"] == result["sessions"]


async def test_delete_report(
    recorder_mock,
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user,
    report_files,
) -> None:
    hass.states.async_set(ENTITY, "1000.0", ATTRS)
    entry = await setup_entry(hass)
    year, quarter = previous_quarter(dt_util.now().date())
    result = await entry.runtime_data.async_generate(year, quarter)
    await hass.async_block_till_done()
    assert hass.states.get(LAST_REPORT).state != "unknown"
    stem = Path(result["xlsx_path"]).stem

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": f"{DOMAIN}/delete", "stem": "../secrets"})
    assert (await ws.receive_json())["error"]["code"] == "invalid_format"

    await ws.send_json({"id": 2, "type": f"{DOMAIN}/delete", "stem": stem})
    response = await ws.receive_json()
    assert response["result"] == {"removed": ["xlsx", "csv"]}
    await hass.async_block_till_done()
    assert not Path(result["xlsx_path"]).exists()
    assert not Path(result["csv_path"]).exists()
    assert entry.runtime_data.reports == {}
    assert hass.states.get(LAST_REPORT).state == "unknown"
    notifications = persistent_notification._async_get_or_create_notifications(hass)
    assert not [n for n in notifications if n.startswith(f"{DOMAIN}_")]

    await ws.send_json({"id": 3, "type": f"{DOMAIN}/delete", "stem": stem})
    assert (await ws.receive_json())["error"]["code"] == "not_found"

    hass_admin_user.groups = []
    await ws.send_json({"id": 4, "type": f"{DOMAIN}/delete", "stem": stem})
    assert (await ws.receive_json())["error"]["code"] == "unauthorized"


async def test_reports_follow_the_device_name(
    recorder_mock,
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    report_files,
) -> None:
    """Renaming the device renames the report; the old file of that quarter goes."""
    from homeassistant.helpers import device_registry as dr

    hass.states.async_set(ENTITY, "1000.0", ATTRS)
    entry = await setup_entry(hass)
    manager = entry.runtime_data
    year, quarter = previous_quarter(dt_util.now().date())
    old = await manager.async_generate(year, quarter)
    assert Path(old["xlsx_path"]).name == f"ere_laadpaal_{year}_q{quarter}.xlsx"

    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    registry.async_update_device(device.id, name_by_user="Alfen Eve")
    assert manager.charger_name == "Alfen Eve"

    new = await manager.async_generate(year, quarter)
    assert new["charger"] == "Alfen Eve"
    assert Path(new["xlsx_path"]).name == f"ere_alfen_eve_{year}_q{quarter}.xlsx"
    assert not Path(old["xlsx_path"]).exists()
    assert not Path(old["csv_path"]).exists()

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": f"{DOMAIN}/reports"})
    result = (await ws.receive_json())["result"]
    assert result["chargers"][0]["title"] == "Alfen Eve"
    [report] = result["reports"]
    assert report["charger"] == "Alfen Eve"
    for path in (new["xlsx_path"], new["csv_path"]):
        Path(path).unlink()
