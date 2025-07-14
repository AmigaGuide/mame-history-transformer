"""
Filename: encoding_utils.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Detects and caches file encodings using the `chardet` library.
Primarily supports MAME XML, Gaming-History XML, and related INI files.

Encodings are stored in a local encodings.json file to avoid repeated detection.
Also provides logic for safely loading and storing these results as part of the
project’s preprocessing pipeline.

This file is part of a student project and is not intended for commercial use.
"""

from pathlib import Path
import chardet
import json

from config import LOG_LEVEL
from logger import setup_logger

log = setup_logger(log_level=LOG_LEVEL)

ENCODING_FILE = Path("data/encodings.json")

def detect_encoding_chardet(file_path: Path) -> str:
    """
    Use chardet to detect the encoding of the given XML or INI file.

    Parameters:
        file_path (Path): Path to the file.

    Returns:
        str: Detected encoding (or 'Unknown' if detection fails).
    """
    with open(file_path, 'rb') as f:
        raw_data = f.read()
        result = chardet.detect(raw_data)
        return result['encoding'] or "Unknown"

def load_or_create_encodings(xml_files: list[Path]) -> dict:
    """
    Load encoding information from a JSON file in /data if it exists.
    Otherwise, detect encodings using chardet and save the results.

    Parameters:
        xml_files (list[Path]): List of XML/INI file paths.

    Returns:
        dict: Dictionary of {filename: encoding}
    """
    if ENCODING_FILE.exists():
        try:
            with open(ENCODING_FILE, 'r', encoding='utf-8') as f:
                encodings = json.load(f)
                log.info("Using cached encodings from encodings.json")
                return encodings
        except (json.JSONDecodeError, IOError):
            log.warning("Failed to read encodings.json. Regenerating.")

    encodings = {}
    for xml_file in xml_files:
        log.info(f"Detecting encoding for {xml_file.name}...")
        encoding = detect_encoding_chardet(xml_file)
        encodings[xml_file.name] = encoding
        log.debug(f"Detected encoding for {xml_file.name}: {encoding}")

    with open(ENCODING_FILE, 'w', encoding='utf-8') as f:
        json.dump(encodings, f, indent=2)

    log.info("Encodings detected and saved to encodings.json")
    return encodings
