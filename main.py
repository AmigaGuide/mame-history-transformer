"""
Filename: main.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Entry point for the XML parsing and classification pipeline. Validates the presence
of required source files, detects encodings, verifies version consistency, logs 
classification summaries, and initiates parsing of the MAME XML dataset.

The output is a clone-aware, classification-filtered list of valid arcade machines
from the MAME XML, suitable for transformation into wiki-compatible JSON.

This file is part of a student project and is not intended for commercial use.
"""

import json
import re
import time
from pathlib import Path
import xml.etree.ElementTree as ET

from config import LOG_LEVEL
from logger import setup_logger, debug_log
from encoding_utils import detect_encoding
from mame_parser import parse_mame_xml
from history_metadata import summarise_ini_classifications
from history_parser import parse_history_xml

log = setup_logger(log_level=LOG_LEVEL)

ENCODINGS_PATH = Path("data/encodings.json")

def check_required_files() -> list[Path] | None:
    """
    Check for the presence of required XML and INI files in the 'data' folder.
    If any are missing, print download instructions.

    Returns:
        list[Path]: List of required file paths, or None if missing.
    """
    data_dir = Path("data")
    filenames = [
        "mame.xml",
        "history.xml",
        "[GAMING HISTORY] Game Or No Game.ini",
        "[GAMING HISTORY] Machine Category.ini",
        "[GAMING HISTORY] Machine Type.ini",
    ]
    missing = [f for f in filenames if not (data_dir / f).is_file()]

    for fname in filenames:
        if fname not in missing:
            debug_log(f"Verified: data/{fname} exists")

    if missing:
        log.error("Missing required files in /data:")
        for fname in missing:
            log.error(f" - {fname}")

        log.info("Instructions:")
        if "mame.xml" in missing:
            log.info("• Download MAME XML from https://www.mamedev.org/release.php")
            log.info("• Extract and rename it to 'mame.xml' in the 'data' folder")
        if "history.xml" in missing:
            log.info("• Download Gaming-History XML from arcade-history.com")
            log.info("• Extract 'history.xml' to the 'data' folder")
        if any(".ini" in f for f in missing):
            log.info("• The same ZIP includes .ini files — extract all three to the 'data' folder.")

        return None

    log.info("All required files found.")
    return [data_dir / f for f in filenames]

def get_xml_version(file_path: Path, root_tag: str) -> str:
    """
    Extract version or build info from the root tag of the XML file.
    """
    try:
        for event, elem in ET.iterparse(file_path, events=('start',)):
            if elem.tag == root_tag:
                return elem.attrib.get("build") or elem.attrib.get("version", "Unknown")
    except ET.ParseError:
        log.error(f"Parse error reading {file_path}")
        return "Parse Error"
    return "Unknown"

def get_ini_version(file_path: Path, encoding: str) -> str:
    """
    Extract version string from top of .ini file.
    """
    try:
        with open(file_path, encoding=encoding) as f:
            for line in f:
                if line.strip().startswith(";;") and "MAME" in line:
                    match = re.search(r"MAME\s+([0-9]+\.[0-9]+)", line)
                    if match:
                        return match.group(1)
    except Exception as e:
        log.warning(f"Could not extract version from {file_path.name}: {e}")
    return "Unknown"

def normalise_version(version_str: str) -> str:
    """
    Normalises version strings to format '0.XXX'
    """
    version_str = version_str.strip()
    version_str = re.sub(r"\s*\(.*?\)", "", version_str)

    if version_str.startswith("0."):
        return version_str

    try:
        version_float = float(version_str)
        return f"{version_float / 10:.3f}"
    except ValueError:
        log.warning(f"Could not normalise version string: {version_str}")
        return "Unknown"

def main():
    log.info("Starting TM470 XML parsing pipeline...")

    required_paths = check_required_files()
    if not required_paths:
        log.error("Aborting. Required files missing.")
        return

    data_dir = Path("data")
    encoding_cache = {}

    # Load existing encodings.json if it exists
    if ENCODINGS_PATH.exists():
        try:
            with open(ENCODINGS_PATH, "r", encoding="utf-8") as f:
                encoding_cache = json.load(f)
            log.info("Loaded encoding cache from encodings.json")
        except (json.JSONDecodeError, IOError):
            log.warning("Could not read encodings.json. Will re-parse all files.")

    updated_encodings = {}

    for file_path in required_paths:
        fname = file_path.name
        stored_entry = encoding_cache.get(fname)
        version = "Unknown"
        encoding = "Unknown"

        # Use previous encoding to extract version
        if stored_entry:
            if fname.endswith(".xml"):
                version = get_xml_version(file_path, "mame" if "mame" in fname.lower() else "history")
            elif fname.endswith(".ini"):
                version = get_ini_version(file_path, stored_entry["encoding"])

            version = normalise_version(version)
            if version != stored_entry.get("version"):
                log.info(f"Version mismatch for {fname}, re-parsing...")
            else:
                debug_log(f"{fname} version matches stored record.")
                updated_encodings[fname] = stored_entry
                continue

        # Detect encoding and version anew
        start = time.perf_counter()
        encoding = detect_encoding(file_path)

        if fname.endswith(".xml"):
            version = get_xml_version(file_path, "mame" if "mame" in fname.lower() else "history")
        elif fname.endswith(".ini"):
            version = get_ini_version(file_path, encoding)

        version = normalise_version(version)
        updated_encodings[fname] = {
            "encoding": encoding,
            "version": version
        }
        end = time.perf_counter()
        log.info(f"Parsed {fname} in {end - start:.2f} seconds")

    # Save new encodings.json
    with open(ENCODINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(updated_encodings, f, indent=2)

    log.info("Saved updated encodings.json")
    log.info("Proceeding to XML parsing...")

    # Pass encodings to downstream modules
    encodings = {k: v["encoding"] for k, v in updated_encodings.items()}

    summary = summarise_ini_classifications(encodings)
    #log.info("INI Classification Summary:")
    #for category, counts in summary.items():
    #    log.info(f"--- {category} ---")
    #    for label, count in sorted(counts.items()):
    #        debug_log(f"    {label}: {count}")

    log.info("Beginning MAME XML parsing...")
    machines = parse_mame_xml(data_dir / "mame.xml", encodings=encodings, max_records=0)
    log.info(f"Final machine count after clone-aware filtering: {len(machines)}")

    log.info("Beginning History XML parsing...")
    parse_history_xml(data_dir / "history.xml", encodings["history.xml"])

if __name__ == "__main__":
    main()
