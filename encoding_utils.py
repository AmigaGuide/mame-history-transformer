"""
Filename: encoding_utils.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Detects the encoding of a given file using the `chardet` library.

This module does not handle any caching or version tracking logic—
it simply returns the encoding of the requested file.

This file is part of a student project and is not intended for commercial use.
"""

from pathlib import Path
import chardet

from logger import debug_log

def detect_encoding(file_path: Path) -> str:
    """
    Detect the encoding of a file using the `chardet` library.

    Parameters:
        file_path (Path): Path to the XML or INI file.

    Returns:
        str: Detected encoding (or 'Unknown' if detection fails).
    """
    debug_log(f"Detecting encoding for: {file_path.name}")

    with open(file_path, 'rb') as f:
        raw_data = f.read()
        result = chardet.detect(raw_data)
        encoding = result['encoding'] or "Unknown"

    debug_log(f"Detected encoding for {file_path.name}: {encoding}")
    return encoding
