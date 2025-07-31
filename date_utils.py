"""
Filename: date_utils.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Purpose: Handle date parsing and normalisation for Gaming-History entries
Usage: Called from history_parser.py to convert raw date strings into YYYY-MM-DD style.

This file is part of a student project and is not intended for commercial use.
"""
import re
from dateutil import parser as date_parser
from logger import setup_logger, debug_log

logger = setup_logger()

def parse_date_string(date_str: str | None, context: str = "") -> str | None:
    """
    Attempts to parse and normalise a date string into one of the following formats:
    - YYYY-MM-DD if day, month and year are all detected
    - YYYY-MM-XX if only year and month are detected
    - YYYY-XX-XX if only year is detected

    Also handles fuzzy or uncertain years (e.g. "198?", "19??") by replacing question marks with 'X'.

    Returns None if no valid date could be parsed.
    This function assumes the input string has already been extracted from
    round brackets in a PORTS entry (e.g. "(July 1991)" or "(19??)").
    """

    if not date_str or not isinstance(date_str, str):
        return None

    original = date_str.strip()
    original = original.rstrip(",")

    # Handle fuzzy years like 198?, 19??, 20??
    if re.fullmatch(r"\d\?\?\?", original) or re.fullmatch(r"\d{2}\?\?", original) or re.fullmatch(r"\d{3}\?", original):
        cleaned = original.replace("?", "X")
        return f"{cleaned}-XX-XX"

    try:
        # Attempt to parse the date using dateutil
        # If parts like month/day are missing, they default to 1
        dt = date_parser.parse(original, fuzzy=True)

        # Use regex to infer what parts were explicitly present in the original string
        month_match = re.search(
            r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
            r"\b0?[1-9]\b|\b1[0-2]\b)", original, re.IGNORECASE
        )
        day_match = re.search(r"\b[0-3]?\d\b(?:st|nd|rd|th)?", original)

        # Return most specific normalised format based on what was found
        if month_match and day_match:
            return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"
        elif month_match:
            return f"{dt.year:04d}-{dt.month:02d}-XX"
        else:
            return f"{dt.year:04d}-XX-XX"

    except (ValueError, OverflowError):
        debug_log(f"Unparsable date '{original}' (context: {context})")
        return None
