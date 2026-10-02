"""Quarter helpers and session reconstruction from hourly statistics.

Pure Python: no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo

from .session_tracker import SOURCE_RECONSTRUCTED, Session

HOUR = timedelta(hours=1)
# Empty hours allowed between two charging hours of the same session.
MAX_EMPTY_HOURS = 1
# More than a 22 kW charger can deliver in an hour; usually a statistics glitch.
SUSPECT_KWH_PER_HOUR = 22.5


@dataclass
class HourRow:
    """One hour of long-term statistics for the meter."""

    start: datetime
    change: float
    state: float | None = None


def quarter_bounds(year: int, quarter: int, tz: tzinfo) -> tuple[datetime, datetime]:
    """Return the local start and (exclusive) end of a quarter."""
    start = datetime(year, 3 * (quarter - 1) + 1, 1, tzinfo=tz)
    if quarter == 4:
        end = datetime(year + 1, 1, 1, tzinfo=tz)
    else:
        end = datetime(year, 3 * quarter + 1, 1, tzinfo=tz)
    return start, end


def quarter_of(day: date) -> tuple[int, int]:
    return day.year, (day.month - 1) // 3 + 1


def previous_quarter(day: date) -> tuple[int, int]:
    year, quarter = quarter_of(day)
    return (year - 1, 4) if quarter == 1 else (year, quarter - 1)


def reconstruct_sessions(rows: list[HourRow], threshold_kwh: float) -> list[Session]:
    """Cluster hours with consumption into sessions.

    This is an estimate on a whole-hour grid, used only for periods in which
    sessions were not recorded live.
    """
    clusters: list[list[HourRow]] = []
    for row in sorted(rows, key=lambda r: r.start):
        if row.change < threshold_kwh:
            continue
        if clusters:
            empty_hours = (row.start - clusters[-1][-1].start) / HOUR - 1
            if empty_hours <= MAX_EMPTY_HOURS:
                clusters[-1].append(row)
                continue
        clusters.append([row])

    sessions = []
    for cluster in clusters:
        first, last = cluster[0], cluster[-1]
        meter_start = None
        if first.state is not None:
            meter_start = round(first.state - first.change, 3)
        sessions.append(
            Session(
                start=first.start,
                end=last.start + HOUR,
                kwh=round(sum(r.change for r in cluster), 2),
                meter_start=meter_start,
                meter_end=last.state,
                source=SOURCE_RECONSTRUCTED,
            )
        )
    return sessions
