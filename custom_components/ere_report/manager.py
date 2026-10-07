"""Runtime for one charge point: track sessions and generate reports."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from pathlib import Path
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
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
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
    CONF_CHARGER_BRAND,
    CONF_CHARGER_MODEL,
    CONF_CHARGER_SERIAL,
    CONF_EAN,
    CONF_ENERGY_ENTITY,
    CONF_HOLDER_NAME,
    CONF_IDLE_MINUTES,
    CONF_MIN_SESSION_KWH,
    CONF_POSTCODE_CITY,
    CONF_REPORT_LANGUAGE,
    DEFAULT_IDLE_MINUTES,
    DEFAULT_MIN_SESSION_KWH,
    DOMAIN,
    EVENT_REPORT_GENERATED,
    REPORT_DIR,
    SIGNAL_UPDATE,
    STORAGE_VERSION,
)
from .history import HourRow, previous_quarter, quarter_bounds, quarter_of
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
        self.min_kwh: float = entry.options.get(
            CONF_MIN_SESSION_KWH, DEFAULT_MIN_SESSION_KWH
        )
        self.tracker = SessionTracker(
            timedelta(
                minutes=entry.options.get(CONF_IDLE_MINUTES, DEFAULT_IDLE_MINUTES)
            ),
            self.min_kwh,
        )
        self.sessions: list[Session] = []
        self.tracking_since: datetime | None = None
        self.quarter_begin_reading: float | None = None
        self._quarter: tuple[int, int] | None = None
        self._last_auto_report: str | None = None
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
                self.hass, self._handle_daily, hour=0, minute=30, second=0
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
        if self._last_auto_report is None:
            # First run after installation: wait for the next quarter change.
            self._last_auto_report = key
        elif self._last_auto_report != key:
            try:
                await self.async_generate(year, quarter)
            except Exception:
                _LOGGER.exception("Could not generate the report for %s", key)
                return
            self._last_auto_report = key
        else:
            return
        self._store.async_delay_save(self._data_to_save, 0)

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
            charger_name=self.entry.title,
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
            self.tracking_since,
            self.min_kwh,
            self.entry.options.get(CONF_REPORT_LANGUAGE, DEFAULT_LANGUAGE),
        )

    async def async_generate(self, year: int, quarter: int) -> dict[str, Any]:
        """Write the report files for a quarter and announce them."""
        tz = dt_util.get_default_time_zone()
        data = await self.async_build_report(year, quarter)
        integration = await async_get_integration(self.hass, DOMAIN)
        version = str(integration.version or "")
        stem = f"ere_{slugify(self.entry.title)}_{year}_q{quarter}"
        folder = Path(self.hass.config.path(REPORT_DIR))
        xlsx_path = folder / f"{stem}.xlsx"
        csv_path = folder / f"{stem}.csv"

        def _write() -> None:
            write_xlsx(data, xlsx_path, tz, version)
            write_csv(data, csv_path, tz)

        await self.hass.async_add_executor_job(_write)

        result = {
            "config_entry_id": self.entry.entry_id,
            "charger": self.entry.title,
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
        links = {
            suffix: async_sign_path(
                self.hass,
                f"/api/{DOMAIN}/{stem}.{suffix}",
                DOWNLOAD_LINK_VALIDITY,
            )
            for suffix in ("xlsx", "csv")
        }
        if self.hass.config.language.startswith("nl"):
            message = (
                f"**{self.entry.title} — Q{quarter} {year}**: "
                f"{data.meter_total:.2f} kWh, {len(data.sessions)} sessies.\n\n"
                f"[Download xlsx]({links['xlsx']}) · [Download csv]({links['csv']})\n\n"
                f"De bestanden staan in `{folder}`."
            )
            title = "ERE-laadrapport"
        else:
            message = (
                f"**{self.entry.title} — Q{quarter} {year}**: "
                f"{data.meter_total:.2f} kWh, {len(data.sessions)} sessions.\n\n"
                f"[Download xlsx]({links['xlsx']}) · [Download csv]({links['csv']})\n\n"
                f"The files are stored in `{folder}`."
            )
            title = "ERE charging report"
        persistent_notification.async_create(
            self.hass,
            message,
            title=title,
            notification_id=f"{DOMAIN}_{self.entry.entry_id}_{year}q{quarter}",
        )
        self.hass.bus.async_fire(EVENT_REPORT_GENERATED, result)
        return result
