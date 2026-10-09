"""Texts for the report files, per language."""

from __future__ import annotations

from .session_tracker import (
    FLAG_INTERRUPTED,
    FLAG_METER_RESET,
    FLAG_ONGOING,
    FLAG_SPLIT,
)

LANGUAGES = ("nl", "en")
DEFAULT_LANGUAGE = "nl"

TEXTS: dict[str, dict[str, object]] = {
    "nl": {
        "days": ["ma", "di", "wo", "do", "vr", "za", "zo"],
        "months": [
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
        ],
        "flags": {
            FLAG_INTERRUPTED: "meting kort onderbroken",
            FLAG_METER_RESET: "afgesloten door tellerreset",
            FLAG_SPLIT: "gesplitst op kwartaalgrens",
            FLAG_ONGOING: "liep nog bij aanmaken rapport",
        },
        "period_joiner": "t/m",
        "title": "ERE-laadrapport — Q{quarter} {year}",
        "sheet_summary": "Samenvatting",
        "sheet_sessions": "Sessies",
        "sheet_months": "Maandtotalen",
        "section_applicant": "Aanvrager",
        "section_charger": "Laadpunt",
        "section_readings": "Meetgegevens",
        "section_notes": "Opmerkingen",
        "name": "Naam",
        "address": "Adres laadlocatie",
        "postcode_city": "Postcode en plaats",
        "ean": "EAN-code aansluiting",
        "brand": "Merk",
        "model": "Type",
        "serial": "Serienummer",
        "meter_begin": "Meterstand begin periode (kWh)",
        "meter_end": "Meterstand eind periode (kWh)",
        "delivered": "Geleverd in periode (kWh)",
        "session_count": "Aantal laadsessies",
        "footer": (
            "Aangemaakt op {generated} door Home Assistant "
            "(ERE Charging Report {version})."
        ),
        "session_headers": [
            "Nr",
            "Dag",
            "Start",
            "Eind",
            "Duur (u)",
            "Meterstand start (kWh)",
            "Meterstand eind (kWh)",
            "kWh",
            "Opmerking",
        ],
        "total": "Totaal",
        "month_headers": ["Maand", "Aantal sessies", "kWh"],
        "csv_columns": [
            "laadpunt",
            "serienummer",
            "ean",
            "start",
            "eind",
            "meterstand_start_kwh",
            "meterstand_eind_kwh",
            "kwh",
            "opmerking",
        ],
        "note_incomplete": (
            "Voorlopig rapport: het kwartaal was nog niet afgelopen bij het aanmaken."
        ),
        "note_no_data": "Geen meetgegevens gevonden voor deze periode.",
        "note_missing": (
            "{missing} van de {expected} uren in de periode hebben geen meetgegevens."
        ),
        "note_negative": "{count} uren met een dalende meterstand (tellerreset?).",
        "note_spike": (
            "Onwaarschijnlijk hoge uurwaarde van {kwh:.1f} kWh op {when}; "
            "mogelijk verbruik uit eerdere uren zonder meetgegevens."
        ),
        "note_mismatch": (
            "Eindstand min beginstand ({by_readings:.2f} kWh) wijkt af van de som "
            "van de uurwaarden ({total:.2f} kWh)."
        ),
        "note_difference": (
            "Controle: de som van de sessies ({sessions} kWh) wijkt {difference} kWh "
            "af van het geleverde totaal volgens de meter ({total} kWh). Het totaal "
            "volgens de meter is leidend."
        ),
    },
    "en": {
        "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "months": [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        "flags": {
            FLAG_INTERRUPTED: "measurement briefly interrupted",
            FLAG_METER_RESET: "closed by meter reset",
            FLAG_SPLIT: "split at quarter boundary",
            FLAG_ONGOING: "still running when the report was made",
        },
        "period_joiner": "to",
        "title": "ERE charging report — Q{quarter} {year}",
        "sheet_summary": "Summary",
        "sheet_sessions": "Sessions",
        "sheet_months": "Monthly totals",
        "section_applicant": "Applicant",
        "section_charger": "Charge point",
        "section_readings": "Meter data",
        "section_notes": "Notes",
        "name": "Name",
        "address": "Address of charging location",
        "postcode_city": "Postcode and city",
        "ean": "EAN code of grid connection",
        "brand": "Brand",
        "model": "Model",
        "serial": "Serial number",
        "meter_begin": "Meter reading at start of period (kWh)",
        "meter_end": "Meter reading at end of period (kWh)",
        "delivered": "Delivered in period (kWh)",
        "session_count": "Number of charging sessions",
        "footer": (
            "Created on {generated} by Home Assistant (ERE Charging Report {version})."
        ),
        "session_headers": [
            "No",
            "Day",
            "Start",
            "End",
            "Duration (h)",
            "Meter at start (kWh)",
            "Meter at end (kWh)",
            "kWh",
            "Remark",
        ],
        "total": "Total",
        "month_headers": ["Month", "Sessions", "kWh"],
        "csv_columns": [
            "charge_point",
            "serial_number",
            "ean",
            "start",
            "end",
            "meter_start_kwh",
            "meter_end_kwh",
            "kwh",
            "remark",
        ],
        "note_incomplete": (
            "Provisional report: the quarter had not ended when it was created."
        ),
        "note_no_data": "No meter data found for this period.",
        "note_missing": (
            "{missing} of the {expected} hours in the period have no meter data."
        ),
        "note_negative": (
            "{count} hours with a decreasing meter reading (meter reset?)."
        ),
        "note_spike": (
            "Implausibly high hourly value of {kwh:.1f} kWh at {when}; possibly "
            "consumption from earlier hours without meter data."
        ),
        "note_mismatch": (
            "End reading minus start reading ({by_readings:.2f} kWh) differs from the "
            "sum of the hourly values ({total:.2f} kWh)."
        ),
        "note_difference": (
            "Check: the sum of the sessions ({sessions} kWh) differs by {difference} "
            "kWh from the delivered total according to the meter ({total} kWh). The "
            "meter total is leading."
        ),
    },
}


def texts(language: str) -> dict[str, object]:
    """Return the texts for a language, falling back to Dutch."""
    return TEXTS.get(language, TEXTS[DEFAULT_LANGUAGE])
