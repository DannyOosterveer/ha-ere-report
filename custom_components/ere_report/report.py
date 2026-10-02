"""Build the quarterly report and write it as xlsx and csv.

Pure Python plus openpyxl: no Home Assistant imports. The report itself is
in Dutch because the ERE scheme is Dutch.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, tzinfo
from pathlib import Path

from .history import (
    HOUR,
    SUSPECT_KWH_PER_HOUR,
    HourRow,
    quarter_bounds,
    reconstruct_sessions,
)
from .session_tracker import (
    FLAG_INTERRUPTED,
    FLAG_METER_RESET,
    FLAG_ONGOING,
    FLAG_SPLIT,
    SOURCE_LIVE,
    SOURCE_RECONSTRUCTED,
    SOURCE_UNOBSERVED,
    Session,
)

DAYS = ["ma", "di", "wo", "do", "vr", "za", "zo"]
MONTHS = [
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
]
SOURCE_LABELS = {
    SOURCE_LIVE: "live gemeten",
    SOURCE_UNOBSERVED: "niet live waargenomen",
    SOURCE_RECONSTRUCTED: "gereconstrueerd uit uurwaarden",
}
FLAG_LABELS = {
    FLAG_INTERRUPTED: "meting kort onderbroken",
    FLAG_METER_RESET: "afgesloten door tellerreset",
    FLAG_SPLIT: "gesplitst op kwartaalgrens",
    FLAG_ONGOING: "liep nog bij aanmaken rapport",
}
DT_FORMAT = "DD-MM-YYYY HH:MM"


@dataclass
class ReportMeta:
    """Who and what the report is about."""

    charger_name: str
    energy_entity: str
    holder_name: str = ""
    address: str = ""
    postcode_city: str = ""
    ean: str = ""
    charger_brand: str = ""
    charger_model: str = ""
    charger_serial: str = ""
    mid_confirmed: bool = False


@dataclass
class ReportData:
    """Everything that ends up in the report files."""

    meta: ReportMeta
    year: int
    quarter: int
    start: datetime
    end: datetime
    generated: datetime
    complete: bool
    meter_begin: float | None
    meter_end: float | None
    meter_total: float
    sessions: list[Session]
    month_meter_kwh: dict[int, float]
    notes: list[str] = field(default_factory=list)

    @property
    def sessions_total(self) -> float:
        return round(sum(s.kwh for s in self.sessions), 2)

    @property
    def unallocated(self) -> float:
        return round(self.meter_total - self.sessions_total, 2)

    @property
    def months(self) -> list[int]:
        first = 3 * (self.quarter - 1) + 1
        return [first, first + 1, first + 2]


def _clip(
    session: Session,
    start: datetime,
    end: datetime,
    meter_begin: float | None,
    meter_end: float | None,
) -> Session | None:
    """Limit a session to the report period, using the boundary meter readings."""
    if session.end <= start or session.start >= end:
        return None
    if session.start < start:
        if meter_begin is None or session.meter_end is None:
            return None
        kwh = max(0.0, min(session.kwh, session.meter_end - meter_begin))
        session = replace(
            session,
            start=start,
            meter_start=meter_begin,
            kwh=round(kwh, 3),
            flags=[*session.flags, FLAG_SPLIT],
        )
    if session.end > end:
        if meter_end is None or session.meter_start is None:
            return None
        kwh = max(0.0, min(session.kwh, meter_end - session.meter_start))
        flags = [f for f in session.flags if f != FLAG_ONGOING]
        session = replace(
            session,
            end=end,
            meter_end=meter_end,
            kwh=round(kwh, 3),
            flags=[*dict.fromkeys([*flags, FLAG_SPLIT])],
        )
    return session if session.kwh > 0 else None


def build_report(
    meta: ReportMeta,
    year: int,
    quarter: int,
    tz: tzinfo,
    now: datetime,
    rows: list[HourRow],
    recorded_sessions: list[Session],
    tracking_since: datetime | None,
    min_kwh: float,
) -> ReportData:
    """Combine statistics and recorded sessions into a report.

    ``rows`` are hourly statistics covering the quarter plus some hours before
    it, so the meter reading at the start of the quarter can be determined.
    """
    start, end = quarter_bounds(year, quarter, tz)
    rows = sorted(rows, key=lambda r: r.start)
    before = [r for r in rows if r.start < start]
    period = [r for r in rows if start <= r.start < end]
    complete = now >= end

    meter_total = round(sum(r.change for r in period), 2)
    meter_begin = None
    if before and before[-1].state is not None:
        meter_begin = before[-1].state
    elif period and period[0].state is not None:
        meter_begin = period[0].state - period[0].change
    meter_end = period[-1].state if period else None
    if meter_begin is not None:
        meter_begin = round(meter_begin, 3)
    if meter_end is not None:
        meter_end = round(meter_end, 3)

    reconstruct_rows = [
        r for r in period if tracking_since is None or r.start + HOUR <= tracking_since
    ]
    sessions = reconstruct_sessions(reconstruct_rows, min_kwh)
    for recorded in recorded_sessions:
        if clipped := _clip(recorded, start, end, meter_begin, meter_end):
            sessions.append(clipped)
    sessions.sort(key=lambda s: s.start)

    month_meter_kwh: dict[int, float] = {}
    for row in period:
        month = row.start.astimezone(tz).month
        month_meter_kwh[month] = month_meter_kwh.get(month, 0.0) + row.change

    data = ReportData(
        meta=meta,
        year=year,
        quarter=quarter,
        start=start,
        end=end,
        generated=now,
        complete=complete,
        meter_begin=meter_begin,
        meter_end=meter_end,
        meter_total=meter_total,
        sessions=sessions,
        month_meter_kwh=month_meter_kwh,
    )
    data.notes = _notes(data, period, now, tz)
    return data


def _notes(
    data: ReportData, period: list[HourRow], now: datetime, tz: tzinfo
) -> list[str]:
    notes = []
    if not data.complete:
        notes.append(
            "Voorlopig rapport: het kwartaal was nog niet afgelopen bij het aanmaken."
        )
    if not data.meta.mid_confirmed:
        notes.append(
            "De gebruiker heeft niet bevestigd dat de meetbron de geïntegreerde "
            "MID-meter van het laadpunt is."
        )
    if not period:
        notes.append("Geen meetgegevens gevonden voor deze periode.")
        return notes

    # Subtract in UTC: local wall-clock arithmetic ignores DST changes.
    period_end = min(data.end, now).astimezone(UTC)
    expected = int((period_end - data.start.astimezone(UTC)) / HOUR)
    if (missing := expected - len(period)) > 0:
        notes.append(
            f"{missing} van de {expected} uren in de periode hebben geen meetgegevens."
        )
    if negative := [r for r in period if r.change < 0]:
        notes.append(f"{len(negative)} uren met een dalende meterstand (tellerreset?).")
    for row in period:
        if row.change > SUSPECT_KWH_PER_HOUR:
            when = row.start.astimezone(tz).strftime("%d-%m-%Y %H:%M")
            notes.append(
                f"Onwaarschijnlijk hoge uurwaarde van {row.change:.1f} kWh op {when}; "
                "mogelijk verbruik uit eerdere uren zonder meetgegevens."
            )
    if data.meter_begin is not None and data.meter_end is not None:
        by_readings = round(data.meter_end - data.meter_begin, 2)
        if abs(by_readings - data.meter_total) > 0.02:
            notes.append(
                f"Eindstand min beginstand ({by_readings:.2f} kWh) wijkt af van de som "
                f"van de uurwaarden ({data.meter_total:.2f} kWh)."
            )
    counts = {
        source: sum(1 for s in data.sessions if s.source == source)
        for source in (SOURCE_RECONSTRUCTED, SOURCE_UNOBSERVED)
    }
    if counts[SOURCE_RECONSTRUCTED]:
        notes.append(
            f"{counts[SOURCE_RECONSTRUCTED]} sessies zijn achteraf gereconstrueerd uit "
            "uurwaarden; begin- en eindtijden zijn afgerond op hele uren."
        )
    if counts[SOURCE_UNOBSERVED]:
        notes.append(
            f"{counts[SOURCE_UNOBSERVED]} sessies zijn niet live waargenomen "
            "(Home Assistant of de sensor was niet beschikbaar); de starttijd is "
            "het laatste moment waarop de meter nog werd gevolgd."
        )
    return notes


def _yes_no(value: bool) -> str:
    return "ja" if value else "nee"


def _period_label(data: ReportData, tz: tzinfo) -> str:
    last_day = (data.end - HOUR).astimezone(tz)
    first_day = data.start.astimezone(tz)
    return (
        f"{first_day.day} {MONTHS[first_day.month - 1]} {first_day.year} t/m "
        f"{last_day.day} {MONTHS[last_day.month - 1]} {last_day.year} ({tz})"
    )


def _remarks(session: Session) -> str:
    return "; ".join(FLAG_LABELS.get(flag, flag) for flag in session.flags)


def write_xlsx(data: ReportData, path: Path, tz: tzinfo, version: str) -> None:
    """Write the report as an Excel workbook with plain values (no formulas)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    title_font = Font(bold=True, size=14)
    bold = Font(bold=True)
    header_fill = PatternFill("solid", start_color="DDEBF7")

    def header(ws, row: int, labels: list[str]) -> None:
        for col, label in enumerate(labels, start=1):
            cell = ws.cell(row=row, column=col, value=label)
            cell.font = bold
            cell.fill = header_fill

    wb = Workbook()
    ws = wb.active
    ws.title = "Samenvatting"
    meta = data.meta
    ws.append([f"ERE-laadrapport — Q{data.quarter} {data.year}"])
    ws["A1"].font = title_font
    ws.append([_period_label(data, tz)])
    ws.append([])

    sections: list[tuple[str, list[tuple[str, object]]]] = [
        (
            "Aanvrager",
            [
                ("Naam", meta.holder_name),
                ("Adres laadlocatie", meta.address),
                ("Postcode en plaats", meta.postcode_city),
                ("EAN-code aansluiting", meta.ean),
            ],
        ),
        (
            "Laadpunt",
            [
                ("Naam", meta.charger_name),
                ("Merk", meta.charger_brand),
                ("Type", meta.charger_model),
                ("Serienummer", meta.charger_serial),
                (
                    "Geïntegreerde MID-meter (verklaring gebruiker)",
                    _yes_no(meta.mid_confirmed),
                ),
                ("Meetbron in Home Assistant", meta.energy_entity),
            ],
        ),
        (
            "Meetgegevens",
            [
                ("Meterstand begin periode (kWh)", data.meter_begin),
                ("Meterstand eind periode (kWh)", data.meter_end),
                ("Geleverd in periode (kWh)", data.meter_total),
                ("Aantal laadsessies", len(data.sessions)),
                ("Som laadsessies (kWh)", data.sessions_total),
                ("Niet aan een sessie toegewezen (kWh)", data.unallocated),
            ],
        ),
    ]
    for title, items in sections:
        ws.append([title])
        ws.cell(row=ws.max_row, column=1).font = bold
        ws.cell(row=ws.max_row, column=1).fill = header_fill
        ws.cell(row=ws.max_row, column=2).fill = header_fill
        for label, value in items:
            ws.append([label, value])
            cell = ws.cell(row=ws.max_row, column=2)
            cell.alignment = Alignment(horizontal="left")
            if label == "Geleverd in periode (kWh)":
                ws.cell(row=ws.max_row, column=1).font = bold
                cell.font = bold
            if isinstance(value, float):
                cell.number_format = "0.00"
        ws.append([])
    if data.notes:
        ws.append(["Opmerkingen"])
        ws.cell(row=ws.max_row, column=1).font = bold
        for note in data.notes:
            ws.append([note])
        ws.append([])
    generated = data.generated.astimezone(tz).strftime("%d-%m-%Y %H:%M")
    ws.append(
        [f"Aangemaakt op {generated} door Home Assistant (ERE-laadrapport {version})."]
    )
    ws.column_dimensions["A"].width = 48
    ws.column_dimensions["B"].width = 36

    ws = wb.create_sheet("Sessies")
    header(
        ws,
        1,
        [
            "Nr",
            "Dag",
            "Start",
            "Eind",
            "Duur (u)",
            "Meterstand start (kWh)",
            "Meterstand eind (kWh)",
            "kWh",
            "Herkomst",
            "Opmerking",
        ],
    )
    for number, session in enumerate(data.sessions, start=1):
        local_start = session.start.astimezone(tz)
        local_end = session.end.astimezone(tz)
        ws.append(
            [
                number,
                DAYS[local_start.weekday()],
                local_start.replace(tzinfo=None),
                local_end.replace(tzinfo=None),
                round((session.end - session.start) / HOUR, 2),
                session.meter_start,
                session.meter_end,
                round(session.kwh, 2),
                SOURCE_LABELS.get(session.source, session.source),
                _remarks(session),
            ]
        )
        row = ws.max_row
        ws.cell(row=row, column=3).number_format = DT_FORMAT
        ws.cell(row=row, column=4).number_format = DT_FORMAT
        for col in (5, 8):
            ws.cell(row=row, column=col).number_format = "0.00"
        for col in (6, 7):
            ws.cell(row=row, column=col).number_format = "0.000"
    ws.append([])
    ws.append(["Totaal", None, None, None, None, None, None, data.sessions_total])
    ws.cell(row=ws.max_row, column=1).font = bold
    ws.cell(row=ws.max_row, column=8).font = bold
    ws.cell(row=ws.max_row, column=8).number_format = "0.00"
    for column, width in zip(
        "ABCDEFGHIJ", (6, 6, 18, 18, 9, 22, 22, 10, 30, 40), strict=True
    ):
        ws.column_dimensions[column].width = width
    ws.freeze_panes = "A2"

    ws = wb.create_sheet("Maandtotalen")
    header(ws, 1, ["Maand", "Aantal sessies", "kWh sessies", "kWh meter"])
    for month in data.months:
        in_month = [s for s in data.sessions if s.start.astimezone(tz).month == month]
        ws.append(
            [
                MONTHS[month - 1],
                len(in_month),
                round(sum(s.kwh for s in in_month), 2),
                round(data.month_meter_kwh.get(month, 0.0), 2),
            ]
        )
    ws.append([])
    ws.append(["Totaal", len(data.sessions), data.sessions_total, data.meter_total])
    for col in range(1, 5):
        ws.cell(row=ws.max_row, column=col).font = bold
    for row in ws.iter_rows(min_row=2, min_col=3, max_col=4):
        for cell in row:
            cell.number_format = "0.00"
    for column, width in zip("ABCD", (14, 16, 14, 14), strict=True):
        ws.column_dimensions[column].width = width

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


CSV_COLUMNS = [
    "laadpunt",
    "serienummer",
    "ean",
    "start",
    "eind",
    "meterstand_start_kwh",
    "meterstand_eind_kwh",
    "kwh",
    "herkomst",
    "opmerking",
]


def write_csv(data: ReportData, path: Path, tz: tzinfo) -> None:
    """Write one line per session, with ISO 8601 timestamps."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for session in data.sessions:
            writer.writerow(
                [
                    data.meta.charger_name,
                    data.meta.charger_serial,
                    data.meta.ean,
                    session.start.astimezone(tz).isoformat(timespec="seconds"),
                    session.end.astimezone(tz).isoformat(timespec="seconds"),
                    "" if session.meter_start is None else f"{session.meter_start:.3f}",
                    "" if session.meter_end is None else f"{session.meter_end:.3f}",
                    f"{session.kwh:.2f}",
                    SOURCE_LABELS.get(session.source, session.source),
                    _remarks(session),
                ]
            )
