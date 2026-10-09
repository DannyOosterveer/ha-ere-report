"""Runtime for one charge point: track sessions and generate reports."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from pathlib import Path
import re
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util, slugify
from homeassistant.util.unit_conversion import EnergyConverter

from .const import (
    CONF_ADDRESS,
    CONF_AUTO_REPORT,
    CONF_CHARGER_BRAND,
    CONF_CHARGER_MODEL,
    CONF_CHARGER_SERIAL,
    CONF_EAN,
    CONF_ENERGY_ENTITY,
    CONF_HOLDER_NAME,
    CONF_IDLE_MINUTES,
    CONF_POSTCODE_CITY,
    CONF_PUSH_TARGETS,
    CONF_REPORT_LANGUAGE,
    DAILY_CHECK_HOUR,
    DEFAULT_IDLE_MINUTES,
    DOMAIN,
    EVENT_REPORT_GENERATED,
    PANEL_URL,
    REPORT_DIR,
    SIGNAL_UPDATE,
    STORAGE_VERSION,
)
from .history import HourRow, previous_quarter, quarter_bounds, quarter_of
from .phones import NOTIFY, async_admin_phones
from .report import ReportData, ReportMeta, build_report, write_csv, write_xlsx
from .report_text import DEFAULT_LANGUAGE
from .session_tracker import Session, SessionTracker

_LOGGER = logging.getLogger(__name__)

TICK_INTERVAL = timedelta(seconds=30)
SAVE_DELAY = 60
# Statistics before the quarter, used to find the meter reading at its start.
LOOKBACK = timedelta(days=14)
STARTUP_CHECK_DELAY = 300
DOWNLOAD_LINK_VALIDITY = timedelta(days=30)


class EreReportManager:
    """Track charging sessions of one meter and build quarterly reports."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.energy_entity: str = entry.data[CONF_ENERGY_ENTITY]
        self.tracker = SessionTracker(
            timedelta(
                minutes=entry.options.get(CONF_IDLE_MINUTES, DEFAULT_IDLE_MINUTES)
            ),
        )
        self.sessions: list[Session] = []
        self.tracking_since: datetime | None = None
        self.quarter_begin_reading: float | None = None
        self._quarter: tuple[int, int] | None = None
        self._last_auto_report: str | None = None
        # Generated reports by file stem, newest last.
        self.reports: dict[str, dict[str, Any]] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._unsubs: list[CALLBACK_TYPE] = []

    @property
    def signal(self) -> str:
        return SIGNAL_UPDATE.format(self.entry.entry_id)

    @property
    def last_session(self) -> Session | None:
        return self.sessions[-1] if self.sessions else None

    @property
    def charger_name(self) -> str:
        """The name the user sees: the device name if they renamed the device."""
        device = dr.async_get(self.hass).async_get_device(
            identifiers={(DOMAIN, self.entry.entry_id)}
        )
        if device and device.name_by_user:
            return device.name_by_user
        return self.entry.title

    def stem(self, year: int, quarter: int) -> str:
        return f"ere_{slugify(self.charger_name)}_{year}_q{quarter}"

    def owns_stem(self, stem: str) -> bool:
        """Whether a report file belongs to this charge point, old names included."""
        names = {self.charger_name, self.entry.title}
        return stem in self.reports or any(
            re.fullmatch(rf"ere_{slugify(name)}_\d{{4}}_q[1-4]", stem) for name in names
        )

    @property
    def last_report(self) -> dict[str, Any] | None:
        if not self.reports:
            return None
        return max(self.reports.values(), key=lambda report: report["generated"])

    @property
    def dutch(self) -> bool:
        return self.hass.config.language.startswith("nl")

    @property
    def sessions_this_quarter(self) -> int:
        now = dt_util.now()
        start, _ = quarter_bounds(*quarter_of(now.date()), now.tzinfo)
        return sum(1 for s in self.sessions if s.start >= start)

    @property
    def quarter_energy(self) -> float | None:
        if self.quarter_begin_reading is None or self.tracker.last_reading is None:
            return None
        return round(
            max(0.0, self.tracker.last_reading - self.quarter_begin_reading), 2
        )

    async def async_start(self) -> None:
        """Restore stored sessions and start following the meter."""
        now = dt_util.utcnow()
        if stored := await self._store.async_load():
            self.sessions = [Session.from_dict(s) for s in stored.get("sessions", [])]
            self.tracker.restore(stored.get("tracker", {}))
            self._last_auto_report = stored.get("last_auto_report")
            self.reports = stored.get("reports", {})
            if since := stored.get("tracking_since"):
                self.tracking_since = datetime.fromisoformat(since)
        if self.tracking_since is None:
            self.tracking_since = now
            self._store.async_delay_save(self._data_to_save, 0)

        self._unsubs = [
            async_track_state_change_event(
                self.hass, [self.energy_entity], self._handle_state_event
            ),
            async_track_time_interval(self.hass, self._handle_tick, TICK_INTERVAL),
            async_track_time_change(
                self.hass,
                self._handle_daily,
                hour=DAILY_CHECK_HOUR,
                minute=0,
                second=0,
            ),
            async_call_later(self.hass, STARTUP_CHECK_DELAY, self._handle_daily),
        ]
        if state := self.hass.states.get(self.energy_entity):
            self._process_state(state, now)
        await self._async_refresh_quarter_begin()

    async def async_stop(self) -> None:
        """Stop following the meter and persist the current state."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        self.tracker.tick(dt_util.utcnow())
        await self._store.async_save(self._data_to_save())

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        return {
            "tracking_since": self.tracking_since.isoformat()
            if self.tracking_since
            else None,
            "sessions": [s.as_dict() for s in self.sessions],
            "tracker": self.tracker.as_dict(),
            "last_auto_report": self._last_auto_report,
            "reports": self.reports,
        }

    @callback
    def _handle_state_event(self, event: Event[EventStateChangedData]) -> None:
        if (state := event.data["new_state"]) is not None:
            # Use the state's own timestamp: the listener may run later.
            self._process_state(state, state.last_updated)

    @callback
    def _process_state(self, state: State, now: datetime) -> None:
        if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self.tracker.mark_gap(now)
            return
        try:
            reading = EnergyConverter.convert(
                float(state.state),
                state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                or UnitOfEnergy.KILO_WATT_HOUR,
                UnitOfEnergy.KILO_WATT_HOUR,
            )
        except (ValueError, KeyError):
            _LOGGER.debug("Ignoring unusable meter state %s", state.state)
            self.tracker.mark_gap(now)
            return
        self._add_closed(self.tracker.update(now, reading))
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)
        async_dispatcher_send(self.hass, self.signal)

    @callback
    def _handle_tick(self, now: datetime) -> None:
        if closed := self.tracker.tick(dt_util.utcnow()):
            self._add_closed(closed)
            self._store.async_delay_save(self._data_to_save, 0)
            async_dispatcher_send(self.hass, self.signal)

    @callback
    def _add_closed(self, closed: list[Session]) -> None:
        for session in closed:
            _LOGGER.debug("Charging session recorded: %s", session)
            self.sessions.append(session)

    async def _handle_daily(self, now: datetime) -> None:
        """Refresh the quarter start reading and create the report when due."""
        await self._async_refresh_quarter_begin()
        year, quarter = previous_quarter(dt_util.now().date())
        key = f"{year}Q{quarter}"
        if self._last_auto_report == key:
            return
        if self._last_auto_report is None or not self.entry.options.get(
            CONF_AUTO_REPORT, True
        ):
            # First run after installation, or automatic reports are switched
            # off: only note the quarter, so switching on later does not
            # report a quarter that has long passed.
            self._last_auto_report = key
        else:
            try:
                result = await self.async_generate(year, quarter)
            except HomeAssistantError as err:
                self._notify_failure(year, quarter, err)
                await self._async_push_failure(year, quarter)
                return
            self._last_auto_report = key
            await self._async_push_report(result)
        self._store.async_delay_save(self._data_to_save, 0)

    async def _async_push(self, title: str, message: str) -> None:
        """Send a push notification that opens the reports page when tapped."""
        if CONF_PUSH_TARGETS in self.entry.options:
            targets = list(self.entry.options[CONF_PUSH_TARGETS])
        else:
            targets = list(await async_admin_phones(self.hass))
        link = f"/{PANEL_URL}"
        for service in targets:
            if not self.hass.services.has_service(NOTIFY, service):
                _LOGGER.warning("Push notification target notify.%s not found", service)
                continue
            try:
                await self.hass.services.async_call(
                    NOTIFY,
                    service,
                    {
                        "title": title,
                        "message": message,
                        # iOS opens "url", Android opens "clickAction".
                        "data": {"url": link, "clickAction": link},
                    },
                    blocking=True,
                )
            except HomeAssistantError:
                _LOGGER.exception("Could not send a push notification to %s", service)

    async def _async_push_report(self, result: dict[str, Any]) -> None:
        period = f"Q{result['quarter']} {result['year']}"
        kwh = f"{result['total_kwh']:.2f}"
        if self.dutch:
            await self._async_push(
                f"ERE-laadrapport {period}",
                f"{self.charger_name}: {kwh.replace('.', ',')} kWh in "
                f"{result['sessions']} sessies. Tik om te downloaden.",
            )
        else:
            await self._async_push(
                f"ERE charging report {period}",
                f"{self.charger_name}: {kwh} kWh in {result['sessions']} sessions. "
                "Tap to download.",
            )

    async def _async_push_failure(self, year: int, quarter: int) -> None:
        if self.dutch:
            await self._async_push(
                "ERE-laadrapport mislukt",
                f"Het rapport Q{quarter} {year} voor {self.charger_name} kon niet "
                "worden gemaakt. Tik voor details.",
            )
        else:
            await self._async_push(
                "ERE charging report failed",
                f"The Q{quarter} {year} report for {self.charger_name} could not be "
                "created. Tap for details.",
            )

    async def _async_fetch_rows(self, start: datetime, end: datetime) -> list[HourRow]:
        result = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            end,
            {self.energy_entity},
            "hour",
            {"energy": UnitOfEnergy.KILO_WATT_HOUR},
            {"state", "change"},
        )
        return [
            HourRow(
                start=dt_util.utc_from_timestamp(row["start"]),
                change=row.get("change") or 0.0,
                state=row.get("state"),
            )
            for row in result.get(self.energy_entity, [])
        ]

    async def _async_refresh_quarter_begin(self) -> None:
        now = dt_util.now()
        current = quarter_of(now.date())
        if self._quarter == current and self.quarter_begin_reading is not None:
            return
        start, _ = quarter_bounds(*current, now.tzinfo)
        rows = await self._async_fetch_rows(
            start - LOOKBACK, start + timedelta(hours=1)
        )
        reading = None
        if before := [r for r in rows if r.start < start and r.state is not None]:
            reading = before[-1].state
        elif rows and rows[0].state is not None:
            reading = rows[0].state - rows[0].change
        self._quarter = current
        self.quarter_begin_reading = reading
        async_dispatcher_send(self.hass, self.signal)

    def _meta(self) -> ReportMeta:
        options = self.entry.options
        return ReportMeta(
            charger_name=self.charger_name,
            energy_entity=self.energy_entity,
            holder_name=options.get(CONF_HOLDER_NAME, ""),
            address=options.get(CONF_ADDRESS, ""),
            postcode_city=options.get(CONF_POSTCODE_CITY, ""),
            ean=options.get(CONF_EAN, ""),
            charger_brand=options.get(CONF_CHARGER_BRAND, ""),
            charger_model=options.get(CONF_CHARGER_MODEL, ""),
            charger_serial=options.get(CONF_CHARGER_SERIAL, ""),
        )

    async def async_build_report(self, year: int, quarter: int) -> ReportData:
        """Collect statistics and recorded sessions for a quarter."""
        tz = dt_util.get_default_time_zone()
        now = dt_util.utcnow()
        start, end = quarter_bounds(year, quarter, tz)
        rows = await self._async_fetch_rows(start - LOOKBACK, end)
        recorded = list(self.sessions)
        if ongoing := self.tracker.open_session(now):
            recorded.append(ongoing)
        return build_report(
            self._meta(),
            year,
            quarter,
            tz,
            now,
            rows,
            recorded,
            self.entry.options.get(CONF_REPORT_LANGUAGE, DEFAULT_LANGUAGE),
        )

    async def async_generate(
        self, year: int, quarter: int, context: Context | None = None
    ) -> dict[str, Any]:
        """Write the report files for a quarter and announce them.

        Raises HomeAssistantError, so a button press or action call shows the
        failure in the UI instead of only in the log.
        """
        tz = dt_util.get_default_time_zone()
        stem = self.stem(year, quarter)
        folder = Path(self.hass.config.path(REPORT_DIR))
        xlsx_path = folder / f"{stem}.xlsx"
        csv_path = folder / f"{stem}.csv"
        try:
            data = await self.async_build_report(year, quarter)
            integration = await async_get_integration(self.hass, DOMAIN)
            version = str(integration.version or "")

            def _write() -> None:
                write_xlsx(data, xlsx_path, tz, version)
                write_csv(data, csv_path, tz)

            await self.hass.async_add_executor_job(_write)
        except Exception as err:
            _LOGGER.exception("Could not generate the report for Q%s %s", quarter, year)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="report_failed",
                translation_placeholders={
                    "period": f"Q{quarter} {year}",
                    "error": str(err) or type(err).__name__,
                },
            ) from err

        result = {
            "config_entry_id": self.entry.entry_id,
            "charger": self.charger_name,
            "year": year,
            "quarter": quarter,
            "complete": data.complete,
            "meter_begin": data.meter_begin,
            "meter_end": data.meter_end,
            "total_kwh": data.meter_total,
            "sessions": len(data.sessions),
            "sessions_kwh": data.sessions_total,
            "xlsx_path": str(xlsx_path),
            "csv_path": str(csv_path),
            "notes": data.notes,
        }
        await self._async_remove_renamed(stem, year, quarter)
        self.reports.pop(stem, None)
        self.reports[stem] = {
            "stem": stem,
            "year": year,
            "quarter": quarter,
            "generated": dt_util.utcnow().isoformat(),
            "complete": data.complete,
            "total_kwh": data.meter_total,
            "sessions": len(data.sessions),
            "notes": data.notes,
        }
        self._store.async_delay_save(self._data_to_save, 0)
        async_dispatcher_send(self.hass, self.signal)
        self._notify_success(stem, year, quarter, data)
        event_data = dict(result)
        # Lets the logbook show the event on the "last report" sensor and device.
        if entity_id := er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, f"{self.entry.entry_id}_last_report"
        ):
            event_data["entity_id"] = entity_id
        self.hass.bus.async_fire(EVENT_REPORT_GENERATED, event_data, context=context)
        return result

    @callback
    def _notify_success(
        self, stem: str, year: int, quarter: int, data: ReportData
    ) -> None:
        links = {
            suffix: async_sign_path(
                self.hass,
                f"/api/{DOMAIN}/{stem}.{suffix}",
                DOWNLOAD_LINK_VALIDITY,
            )
            for suffix in ("xlsx", "csv")
        }
        if self.dutch:
            title = "ERE-laadrapport"
            summary = f"{data.meter_total:.2f} kWh, {len(data.sessions)} sessies."
            all_reports = "Alle rapporten"
        else:
            title = "ERE charging report"
            summary = f"{data.meter_total:.2f} kWh, {len(data.sessions)} sessions."
            all_reports = "All reports"
        persistent_notification.async_create(
            self.hass,
            (
                f"**{self.charger_name} — Q{quarter} {year}**: {summary}\n\n"
                f"[Download xlsx]({links['xlsx']}) · [Download csv]({links['csv']})"
                f" · [{all_reports}](/{PANEL_URL})"
            ),
            title=title,
            notification_id=f"{DOMAIN}_{self.entry.entry_id}_{year}q{quarter}",
        )

    async def _async_remove_renamed(self, stem: str, year: int, quarter: int) -> None:
        """Remove this quarter's report saved under a previous charge point name.

        Making a report again replaces the old one; after a rename the file
        name differs, so the old files would otherwise linger as a duplicate.
        """
        suffix = f"_{year}_q{quarter}"
        old_stems = {
            old for old in self.reports if old.endswith(suffix) and old != stem
        }
        title_stem = f"ere_{slugify(self.entry.title)}{suffix}"
        if title_stem != stem:
            old_stems.add(title_stem)
        if not old_stems:
            return
        folder = Path(self.hass.config.path(REPORT_DIR))

        def _remove() -> None:
            for old in old_stems:
                for ext in ("xlsx", "csv"):
                    (folder / f"{old}.{ext}").unlink(missing_ok=True)

        await self.hass.async_add_executor_job(_remove)
        for old in old_stems:
            self.reports.pop(old, None)

    @callback
    def forget_report(self, stem: str, year: int, quarter: int) -> None:
        """Drop a deleted report and its notification, whose links no longer work."""
        self.reports.pop(stem, None)
        persistent_notification.async_dismiss(
            self.hass, f"{DOMAIN}_{self.entry.entry_id}_{year}q{quarter}"
        )
        self._store.async_delay_save(self._data_to_save, 0)
        async_dispatcher_send(self.hass, self.signal)

    @callback
    def _notify_failure(self, year: int, quarter: int, err: Exception) -> None:
        if self.dutch:
            title = "ERE-laadrapport mislukt"
            message = (
                f"Het rapport voor **{self.charger_name} — Q{quarter} {year}** kon "
                f"niet automatisch worden gemaakt.\n\n{err}\n\nProbeer het opnieuw via "
                f"[ERE-rapporten](/{PANEL_URL}); details staan in het logboek."
            )
        else:
            title = "ERE charging report failed"
            message = (
                f"The report for **{self.charger_name} — Q{quarter} {year}** could not "
                f"be created automatically.\n\n{err}\n\nTry again from "
                f"[ERE reports](/{PANEL_URL}); details are in the log."
            )
        persistent_notification.async_create(
            self.hass,
            message,
            title=title,
            notification_id=f"{DOMAIN}_{self.entry.entry_id}_{year}q{quarter}",
        )
