"""
Filename: encoding_utils.py
Version: 1.0.0
Last modified: 2025-09-10
Author: Jason (XtC) Skelly (Open University TM470, 2025)

Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Purpose:
Detect the text encoding of a file using the `chardet` library. This module is
deliberately narrow in scope: it does not handle caching, version tracking, or
fallback logic—only detection.

Key behaviours:
- Reads file bytes and returns `chardet.detect(...).get('encoding')` or "Unknown".
- Emits lightweight debug logs for traceability.

Exports:
- detect_encoding(file_path: Path) -> str

Licence:
This file forms part of a student project and is not intended for commercial use.
See repository LICENCE for details.
"""

from __future__ import annotations

from pathlib import Path  # stdlib
import chardet            # third-party

#from logger import debug_log  # local
from mht.utils.logger import debug_log

__all__ = ["detect_encoding"]


def detect_encoding(file_path: Path) -> str:
    """
    Detect the encoding of a file using `chardet`.

    Parameters:
        file_path: Path to the XML/INI (or other text) file.

    Returns:
        Detected encoding label (e.g. "UTF-8", "windows-1252"), or "Unknown" if
        chardet does not provide an encoding.
    """
    debug_log(f"Detecting encoding for: {file_path.name}")

    with open(file_path, "rb") as f:
        raw_data = f.read()
        result = chardet.detect(raw_data)
        encoding = result.get("encoding") or "Unknown"

    debug_log(f"Detected encoding for {file_path.name}: {encoding}")
    return encoding
