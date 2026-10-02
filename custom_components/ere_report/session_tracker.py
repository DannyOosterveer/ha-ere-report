"""Charging session detection from a cumulative kWh meter.

Pure Python on purpose: no Home Assistant imports, so the logic can be
tested by replaying meter readings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

SOURCE_LIVE = "live"
SOURCE_UNOBSERVED = "unobserved"
SOURCE_RECONSTRUCTED = "reconstructed"

FLAG_INTERRUPTED = "interrupted"
FLAG_METER_RESET = "meter_reset"
FLAG_SPLIT = "split"
FLAG_ONGOING = "ongoing"

# Meter jitter below this is not treated as a counter reset.
RESET_TOLERANCE_KWH = 0.01


@dataclass
class Session:
    """A finished (or clipped) charging session."""

    start: datetime
    end: datetime
    kwh: float
    meter_start: float | None = None
    meter_end: float | None = None
    source: str = SOURCE_LIVE
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "kwh": self.kwh,
            "meter_start": self.meter_start,
            "meter_end": self.meter_end,
            "source": self.source,
            "flags": list(self.flags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        return cls(
            start=datetime.fromisoformat(data["start"]),
            end=datetime.fromisoformat(data["end"]),
            kwh=data["kwh"],
            meter_start=data.get("meter_start"),
            meter_end=data.get("meter_end"),
            source=data.get("source", SOURCE_LIVE),
            flags=list(data.get("flags", [])),
        )


@dataclass
class _OpenSession:
    start: datetime
    meter_start: float
    meter_end: float
    last_increase: datetime
    source: str = SOURCE_LIVE
    flags: list[str] = field(default_factory=list)


class SessionTracker:
    """Turn a stream of meter readings into charging sessions.

    A session starts when the meter rises and ends once it has not risen for
    ``idle_timeout``. Readings that arrive after a period without observation
    (restart, unavailable sensor) are recorded as ``unobserved`` instead of
    being presented as if they were seen live.
    """

    def __init__(self, idle_timeout: timedelta, min_kwh: float) -> None:
        self.idle_timeout = idle_timeout
        self.min_kwh = min_kwh
        self.last_reading: float | None = None
        self.last_seen: datetime | None = None
        self._open: _OpenSession | None = None
        self._gap_since: datetime | None = None

    @property
    def active(self) -> bool:
        return self._open is not None

    def open_session(self, now: datetime) -> Session | None:
        """Return the running session as if it ended now."""
        if self._open is None:
            return None
        return self._to_session(self._open, end=now, extra_flag=FLAG_ONGOING)

    def mark_gap(self, since: datetime | None) -> None:
        """Note that readings were not observed from ``since`` onwards."""
        if self._gap_since is None:
            self._gap_since = since or self.last_seen

    def update(self, now: datetime, reading: float) -> list[Session]:
        """Process a meter reading; return sessions that were closed by it."""
        closed: list[Session] = []
        gap_since, self._gap_since = self._gap_since, None
        self.last_seen = now

        if self.last_reading is None:
            self.last_reading = reading
            return closed

        delta = reading - self.last_reading
        if delta < -RESET_TOLERANCE_KWH:
            closed += self._close(FLAG_METER_RESET)
            self.last_reading = reading
            return closed
        if delta <= 0:
            return closed

        if gap_since is not None:
            if self._open and now - self._open.last_increase < self.idle_timeout:
                self._open.flags.append(FLAG_INTERRUPTED)
            else:
                closed += self._close()
                if delta < self.min_kwh:
                    self.last_reading = reading
                    return closed
                self._open = _OpenSession(
                    start=gap_since,
                    meter_start=self.last_reading,
                    meter_end=self.last_reading,
                    last_increase=now,
                    source=SOURCE_UNOBSERVED,
                )

        if self._open is None:
            self._open = _OpenSession(
                start=now,
                meter_start=self.last_reading,
                meter_end=self.last_reading,
                last_increase=now,
            )
        self._open.meter_end = reading
        self._open.last_increase = now
        self.last_reading = reading
        return closed

    def tick(self, now: datetime) -> list[Session]:
        """Close the running session when the meter has been idle long enough."""
        if self._gap_since is None:
            self.last_seen = now
        if self._open and now - self._open.last_increase >= self.idle_timeout:
            return self._close()
        return []

    def _close(self, flag: str | None = None) -> list[Session]:
        current, self._open = self._open, None
        if current is None:
            return []
        session = self._to_session(current, end=current.last_increase, extra_flag=flag)
        return [session] if session.kwh >= self.min_kwh else []

    @staticmethod
    def _to_session(
        current: _OpenSession, end: datetime, extra_flag: str | None
    ) -> Session:
        flags = list(dict.fromkeys(current.flags))
        if extra_flag:
            flags.append(extra_flag)
        return Session(
            start=current.start,
            end=end,
            kwh=round(current.meter_end - current.meter_start, 3),
            meter_start=current.meter_start,
            meter_end=current.meter_end,
            source=current.source,
            flags=flags,
        )

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "last_reading": self.last_reading,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "open": None,
        }
        if self._open:
            data["open"] = {
                "start": self._open.start.isoformat(),
                "meter_start": self._open.meter_start,
                "meter_end": self._open.meter_end,
                "last_increase": self._open.last_increase.isoformat(),
                "source": self._open.source,
                "flags": list(self._open.flags),
            }
        return data

    def restore(self, data: dict[str, Any]) -> None:
        """Restore state saved by ``as_dict`` and treat the downtime as a gap."""
        self.last_reading = data.get("last_reading")
        if last_seen := data.get("last_seen"):
            self.last_seen = datetime.fromisoformat(last_seen)
        if current := data.get("open"):
            self._open = _OpenSession(
                start=datetime.fromisoformat(current["start"]),
                meter_start=current["meter_start"],
                meter_end=current["meter_end"],
                last_increase=datetime.fromisoformat(current["last_increase"]),
                source=current.get("source", SOURCE_LIVE),
                flags=list(current.get("flags", [])),
            )
        self._gap_since = self.last_seen
