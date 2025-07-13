from pathlib import Path
import xml.etree.ElementTree as ET
import re
import time
import logging

from config import LOG_LEVEL
from encoding_utils import load_or_create_encodings
from mame_parser import parse_mame_xml
from history_metadata import summarise_ini_classifications
from logger import setup_logger

log = setup_logger(log_level=LOG_LEVEL)

def check_required_files() -> bool:
    """
    Check for the presence of required XML and INI files in the 'data' folder.
    If any are missing, print download instructions.

    Returns:
        bool: True if all required files are present, False otherwise.
    """
    data_dir = Path("data")
    required_files = [
        "mame.xml",
        "history.xml",
        "[GAMING HISTORY] Game Or No Game.ini",
        "[GAMING HISTORY] Machine Category.ini",
        "[GAMING HISTORY] Machine Type.ini",
    ]

    missing = []
    for fname in required_files:
        file_path = data_dir / fname
        if not file_path.is_file():
            missing.append(fname)
        else:
            log.debug(f"Verified: data/{fname} exists")

    if missing:
        log.error("Missing required files in /data:")
        for fname in missing:
            log.error(f" - {fname}")

        log.info("Instructions:")
        if "mame.xml" in missing:
            log.info("• Download the MAME XML from https://www.mamedev.org/release.php")
            log.info("• Extract the file from the mameXXXXlx.zip archive")
            log.info("• Rename the extracted file to 'mame.xml'")
            log.info("• Move it to the 'data' folder")

        if "history.xml" in missing:
            log.info("• Download the Gaming-History XML from:")
            log.info("  https://www.arcade-history.com/index.php?page=download")
            log.info("• Extract 'history.xml' from inside the 'history' folder of the ZIP")
            log.info("• Move it to the 'data' folder")

        if any(".ini" in f for f in missing):
            log.info("• The Gaming-History ZIP also includes .ini classification files.")
            log.info("• Extract all three .ini files and place them in the 'data' folder.")

        return False

    log.info("All required files found.")
    return True

def get_xml_version(file_path: Path, root_tag: str) -> str:
    """
    Extract version or build info from the root tag of the XML file.

    Parameters:
        file_path (Path): Path to the XML file.
        root_tag (str): Expected name of the root element.

    Returns:
        str: Version or build value, or 'Unknown' if not found.
    """
    try:
        for event, elem in ET.iterparse(file_path, events=('start',)):
            if elem.tag == root_tag:
                return elem.attrib.get("build") or elem.attrib.get("version", "Unknown")
    except ET.ParseError:
        log.error(f"Parse error reading {file_path}")
        return "Parse Error"
    return "Unknown"

def normalise_version(version_str: str) -> str:
    """
    Normalises version strings to match MAME's format (e.g. '0.278').

    Parameters:
        version_str (str): Raw version string from XML attribute.

    Returns:
        str: Normalised version string in the format '0.XXX'.
    """
    version_str = version_str.strip()
    version_str = re.sub(r"\s*\(.*?\)", "", version_str)

    if version_str.startswith("0."):
        return version_str

    try:
        version_float = float(version_str)
        normalised = version_float / 10
        return f"{normalised:.3f}"
    except ValueError:
        log.warning(f"Could not normalise version string: {version_str}")
        return "Unknown"

def main():
    """
    Entry point for the TM470 XML parsing pipeline.

    Validates file presence, detects encodings, extracts version info,
    logs .ini classification summaries, and parses MAME XML machines.
    """
    log.info("Starting TM470 XML parsing pipeline...")

    if not check_required_files():
        log.error("Aborting. Required files missing.")
        return

    data_dir = Path("data")
    mame_file = data_dir / "mame.xml"
    history_file = data_dir / "history.xml"
    xml_files = [mame_file, history_file]

    start_enc = time.perf_counter()
    encodings = load_or_create_encodings(xml_files + list(data_dir.glob("*.ini")))
    end_enc = time.perf_counter()

    log.info("Detected File Encodings:")
    for fname, encoding in encodings.items():
        log.info(f"{fname}: {encoding}")
    log.info(f"Encoding detection completed in {end_enc - start_enc:.2f} seconds")

    mame_version_raw = get_xml_version(mame_file, "mame")
    history_version_raw = get_xml_version(history_file, "history")

    mame_version = normalise_version(mame_version_raw)
    history_version = normalise_version(history_version_raw)

    log.info(f"MAME XML version:      {mame_version_raw}")
    log.info(f"History XML version:   {history_version_raw}")
    log.info(f"Normalised MAME version:    {mame_version}")
    log.info(f"Normalised History version: {history_version}")

    if mame_version != history_version:
        log.warning("Version mismatch: MAME and Gaming-History XML versions differ.")

    summary = summarise_ini_classifications()
    log.info("INI Classification Summary:")
    for category, counts in summary.items():
        log.info(f"--- {category} ---")
        for label, count in sorted(counts.items()):
            log.debug(f"    {label}: {count}")

    log.info("Beginning MAME XML parsing...")
    #start_parse = time.perf_counter()
    machines = parse_mame_xml(mame_file, max_records=0)
    #end_parse = time.perf_counter()

    #log.info(f"MAME XML parsing completed in {end_parse - start_parse:.2f} seconds")
    log.info(f"Final machine count after clone-aware filtering: {len(machines)}")

if __name__ == "__main__":
    main()
