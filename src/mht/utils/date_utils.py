"""
Filename: date_utils.py
Version: 1.0.0
Last modified: 2025-09-10
Author: Jason (XtC) Skelly (Open University TM470, 2025)

Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Purpose:
Parse and normalise fuzzy date strings from Gaming-History PORTS entries into
canonical forms suitable for downstream processing and wiki rendering.

Key behaviours:
- Accepts free-form dates (e.g. "July 1991", "Dec. 6, 2007") and returns:
  YYYY-MM-DD when day+month+year are present; YYYY-MM-XX for year+month;
  YYYY-XX-XX for year-only.
- Handles uncertain years (e.g. "198?", "19??") by converting '?' to 'X'
  and returning YYYY-XX-XX.
- Returns None when no valid date can be inferred and logs a DEBUG note
  with calling context.

Inputs:
- Raw date substrings already extracted from parentheses in PORTS lines.

Outputs:
- Normalised date strings or None (no side effects beyond logging).

Logging:
- Uses logger.setup_logger() and debug_log(); verbosity governed by config.LOG_LEVEL.

Licence:
This file forms part of a student project and is not intended for commercial use.
See repository LICENCE for details.
"""

from __future__ import annotations

import re
from dateutil import parser as date_parser

#from logger import setup_logger, debug_log
from mht.utils.logger import setup_logger, debug_log

__all__ = ["parse_date_string"]

logger = setup_logger()


def parse_date_string(date_str: str | None, context: str = "") -> str | None:
    """
    Normalise a PORTS-style date substring.

    Returns one of:
      - "YYYY-MM-DD"  when day, month, and year are present
      - "YYYY-MM-XX"  when month and year are present
      - "YYYY-XX-XX"  when only year is present
      - None          when no valid date can be inferred

    Also handles fuzzy/uncertain years (e.g. "198?", "19??") by replacing
    '?' with 'X' and returning "YYYY-XX-XX".

    Assumptions:
    - The input has already been extracted from parentheses in a PORTS row,
      e.g. "(July 1991)" or "(19??)".

    Parameters:
        date_str: The raw date substring to interpret.
        context:  Short identifier (e.g. system/machine) for debug logs.

    Returns:
        Normalised date string or None.
    """
    if not date_str or not isinstance(date_str, str):
        return None

    original = date_str.strip()
    original = original.rstrip(",")

    # Handle fuzzy years like 198?, 19??, 20?? (replace '?' with 'X')
    if (
        re.fullmatch(r"\d\?\?\?", original)
        or re.fullmatch(r"\d{2}\?\?", original)
        or re.fullmatch(r"\d{3}\?", original)
    ):
        cleaned = original.replace("?", "X")
        return f"{cleaned}-XX-XX"

    try:
        # Parse with dateutil; missing components will default (e.g. day=1)
        dt = date_parser.parse(original, fuzzy=True)

        # Heuristics: detect whether month/day tokens actually appeared
        month_match = re.search(
            r"(?:\bjan|\bfeb|\bmar|\bapr|\bmay|\bjun|\bjul|\baug|\bsep|\boct|\bnov|\bdec|\b0?[1-9]\b|\b1[0-2]\b)",
            original,
            re.IGNORECASE,
        )
        day_match = re.search(r"\b[0-3]?\d\b(?:st|nd|rd|th)?", original, re.IGNORECASE)

        if month_match and day_match:
            return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"
        elif month_match:
            return f"{dt.year:04d}-{dt.month:02d}-XX"
        else:
            return f"{dt.year:04d}-XX-XX"

    except (ValueError, OverflowError):
        debug_log(f"Unparsable date '{original}' (context: {context})")
        return None
