"""
Filename: date_utils.py
Version: 2.0.0
Last modified: 2025-09-25
Author: XtC

Purpose:
Normalise free-form GH date snippets into 'YYYY[-MM[-DD]]' with 'XX' placeholders.
Accepts: year-only, year+month (numeric or name), full dates (numeric or with month name),
and fuzzy years like 19??/198?. Rejects weekdays, ranges, quarters/seasons, month-only.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from .logger import setup_logger, debug_log

__all__ = ["parse_date_string"]

_logger = setup_logger()

# --- Month name support (case-insensitive, optional trailing dot for abbreviations) ---
_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_MONTH_TOKEN = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sept?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_MONTH_TOKEN_DOT = rf"{_MONTH_TOKEN}\.?"  # allow trailing dot on abbreviations

# --- Precompiled patterns (accept) ---
FUZZY_YEAR = re.compile(r"^(?:\d\?\?\?|\d{2}\?\?|\d{3}\?)$")   # 1???, 19??, 198?
YEAR_ONLY = re.compile(r"^\d{4}$")
YEAR_MONTH_NUM = re.compile(r"^(\d{4})[-/](0?[1-9]|1[0-2])$")
NUMERIC_FULL = re.compile(
    r"^(?:"
    r"(?P<y>\d{4})[-/](?P<m>0?[1-9]|1[0-2])[-/](?P<d>0?[1-9]|[12]\d|3[01])"   # ISO: YYYY-M-D
    r"|"
    r"(?P<a>\d{1,2})[-/](?P<b>\d{1,2})[-/](?P<y2>\d{4})"                       # D-M-YYYY or M-D-YYYY
    r")$"
)

MONTH_NAME_YEAR = re.compile(
    rf"^(?P<mon>{_MONTH_TOKEN_DOT})\s*(?P<year>\d{{4}})$",
    re.IGNORECASE,
)

DAY_MONTH_NAME_YEAR = re.compile(
    rf"^(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s*(?P<mon>{_MONTH_TOKEN_DOT})\s*,?\s*(?P<year>\d{{4}})$",
    re.IGNORECASE,
)

MONTH_NAME_DAY_YEAR = re.compile(
    rf"^(?P<mon>{_MONTH_TOKEN_DOT})\s*,?\s*(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(?P<year>\d{{4}})$",
    re.IGNORECASE,
)

MONTH_NAME_UNKNOWN_DAY_YEAR = re.compile(
    rf"^(?P<mon>{_MONTH_TOKEN_DOT})\s*,?\s*\?\?\s*,?\s*(?P<year>\d{{4}})$",
    re.IGNORECASE,
)

UNKNOWN_MONTH_UNKNOWN_DAY_YEAR = re.compile(
    r"^(?:\?{3})\.?\s*,?\s*\?{2}\s*,?\s*(?P<year>\d{4})$",
    re.IGNORECASE,
)

# --- Precompiled patterns (reject) ---
WEEKDAY = re.compile(
    r"\b(?:mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:r|rs|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
    re.IGNORECASE,
)
QUARTER_SEASON = re.compile(r"\bQ[1-4]\b|\b(?:spring|summer|autumn|fall|winter)\b", re.IGNORECASE)
MONTH_ONLY = re.compile(rf"^(?:{_MONTH_TOKEN_DOT})$", re.IGNORECASE)

# Helper: count distinct 4-digit years (reject ranges like 1991/1992)
FOUR_DIGIT_YEAR = re.compile(r"\b\d{4}\b")


def _month_num(mon_token: str) -> Optional[int]:
    k = mon_token.rstrip(".").lower()
    return _MONTHS.get(k)


def _fmt(y: int, m: Optional[int] = None, d: Optional[int] = None) -> str:
    if m is None:
        return f"{y:04d}-XX-XX"
    if d is None:
        return f"{y:04d}-{m:02d}-XX"
    return f"{y:04d}-{m:02d}-{d:02d}"


def _validate_day(y: int, m: int, d: int) -> bool:
    try:
        date(y, m, d)
        return True
    except ValueError:
        return False


def parse_date_string(date_str: str | None, context: str = "") -> str | None:
    """Return 'YYYY[-MM[-DD]]' (with 'XX' placeholders) or None on rejection; logs DEBUG on rejection."""
    if not isinstance(date_str, str):
        return None

    s = date_str.strip()
    if not s:
        return None

    # strip any leading quotes
    s = re.sub(r'^[\'"]+', '', s)

    # strip trailing punctuation like commas/semicolons/quotes (possibly repeated)
    s = re.sub(r'[,\.;:\'"]+\s*$', '', s).strip()

    # collapse internal runs of whitespace
    s = re.sub(r'\s+', ' ', s)

    # 1) Fuzzy year like 198? / 19??
    if FUZZY_YEAR.fullmatch(s):
        return f"{s.replace('?', 'X')}-XX-XX"

    # 2) Rejectors: weekdays, quarters/seasons, month-only, multiple 4-digit years (ranges)
    if WEEKDAY.search(s) or QUARTER_SEASON.search(s) or MONTH_ONLY.fullmatch(s):
        debug_log(f"Unparsable date '{s}' (context: {context})")
        return None
    if len(FOUR_DIGIT_YEAR.findall(s)) >= 2:
        debug_log(f"Unparsable date range/multi-year '{s}' (context: {context})")
        return None

    # 3) Year only
    m = YEAR_ONLY.fullmatch(s)
    if m:
        return _fmt(int(s))

    # 4) Year + month (numeric)
    m = YEAR_MONTH_NUM.fullmatch(s)
    if m:
        y = int(m.group(1))
        mm = int(m.group(2))
        return _fmt(y, mm)

    # 5) Month name + year
    m = MONTH_NAME_YEAR.fullmatch(s)
    if m:
        mm = _month_num(m.group("mon"))
        if mm:
            return _fmt(int(m.group("year")), mm)
        debug_log(f"Unparsable month token '{s}' (context: {context})")
        return None

    m = MONTH_NAME_UNKNOWN_DAY_YEAR.fullmatch(s)
    if m:
        mm = _month_num(m.group("mon"))
        if mm:
            return _fmt(int(m.group("year")), mm)
        debug_log(f"Unparsable month token '{s}' (context: {context})")
        return None

    m = UNKNOWN_MONTH_UNKNOWN_DAY_YEAR.fullmatch(s)
    if m:
        return _fmt(int(m.group("year")))  # YYYY-XX-XX

    # 6) Day MonthName Year  (UK style)
    m = DAY_MONTH_NAME_YEAR.fullmatch(s)
    if m:
        dd = int(m.group("day"))
        mm = _month_num(m.group("mon"))
        yy = int(m.group("year"))
        if not mm or not _validate_day(yy, mm, dd):
            debug_log(f"Invalid calendar date '{s}' (context: {context})")
            return None
        return _fmt(yy, mm, dd)

    # 7) MonthName Day Year  (US style with name)
    m = MONTH_NAME_DAY_YEAR.fullmatch(s)
    if m:
        dd = int(m.group("day"))
        mm = _month_num(m.group("mon"))
        yy = int(m.group("year"))
        if not mm or not _validate_day(yy, mm, dd):
            debug_log(f"Invalid calendar date '{s}' (context: {context})")
            return None
        return _fmt(yy, mm, dd)

    # 8) Full numeric dates (ISO or D/M/Y or M/D/Y) with UK bias on ambiguity
    m = NUMERIC_FULL.fullmatch(s)
    if m:
        if m.group("y"):  # ISO-like: YYYY-M-D
            yy = int(m.group("y"))
            mm = int(m.group("m"))
            dd = int(m.group("d"))
        else:
            a = int(m.group("a"))
            b = int(m.group("b"))
            yy = int(m.group("y2"))
            # If one token > 12, that must be the day
            if a > 12 and b <= 12:
                dd, mm = a, b
            elif b > 12 and a <= 12:
                dd, mm = b, a
            else:
                # Ambiguous: UK bias (day-first)
                dd, mm = a, b
        if not _validate_day(yy, mm, dd):
            debug_log(f"Invalid calendar date '{s}' (context: {context})")
            return None
        return _fmt(yy, mm, dd)

    # 9) No match → reject
    debug_log(f"Unparsable date '{s}' (context: {context})")
    return None
