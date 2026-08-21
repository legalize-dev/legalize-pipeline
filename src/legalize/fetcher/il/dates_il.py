"""Hebrew date parsing and conversion utilities for Israel (il)."""

import re
from datetime import date

GEMATRIA = {
    "א": 1,
    "ב": 2,
    "ג": 3,
    "ד": 4,
    "ה": 5,
    "ו": 6,
    "ז": 7,
    "ח": 8,
    "ט": 9,
    "י": 10,
    "כ": 20,
    "ל": 30,
    "מ": 40,
    "נ": 50,
    "ס": 60,
    "ע": 70,
    "פ": 80,
    "צ": 90,
    "ק": 100,
    "ר": 200,
    "ש": 300,
    "ת": 400,
}


def hebrew_year_to_gregorian(hebrew_year_str: str) -> int:
    """Converts a Hebrew calendar year string to a Gregorian year.

    Examples:
        התש"י -> 1950
        התשמ"ב -> 1982
        התשפ"ה -> 2025
    """
    clean = re.sub(r"[^א-ת\"\'׳״]", "", hebrew_year_str)
    has_thousands = False
    if clean.startswith("ה") and "ת" in clean:
        has_thousands = True
        clean = clean[1:]

    val = 0
    for char in clean:
        if char in GEMATRIA:
            val += GEMATRIA[char]

    hebrew_year = val
    if has_thousands or hebrew_year < 1000:
        hebrew_year += 5000

    return hebrew_year - 3760


def parse_gregorian_date(date_str: str) -> date | None:
    """Parses standard ISO or OData timestamp formats into date object."""
    if not date_str:
        return None
    try:
        # Handle OData DateTimeOffset like 2014-09-10T14:26:43.75+03:00
        # Just extract the first 10 characters (YYYY-MM-DD)
        iso_str = date_str[:10]
        return date.fromisoformat(iso_str)
    except ValueError:
        return None
