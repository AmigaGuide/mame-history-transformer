from pathlib import Path
import xml.etree.ElementTree as ET
import re

from encoding_utils import load_or_create_encodings
from mame_parser import parse_mame_xml
from logger import setup_logger

log = setup_logger()


def check_required_files() -> bool:
    """
    Check for the presence of required XML and INI files in the 'data' folder.

    Returns:
        bool: True if all required files are found, False otherwise.
    """
    data_dir = Path("data")
    required_files = {
        "mame.xml": "MAME XML dataset",
        "history.xml": "Gaming-History XML dataset",
        "[GAMING HISTORY] Game Or No Game.ini": "Gaming-History classification: Game Or No Game",
        "[GAMING HISTORY] Machine Category.ini": "Gaming-History classification: Machine Category",
        "[GAMING HISTORY] Machine Type.ini": "Gaming-History classification: Machine Type",
    }

    missing = []

    for fname, description in required_files.items():
        file_path = data_dir / fname
        if not file_path.is_file():
            missing.append((fname, description))
        else:
            log.info(f"Found file: data/{fname}")

    if missing:
        log.error("Missing required files in /data:")
        for fname, desc in missing:
            log.error(f" - {fname} ({desc})")

        log.info("Instructions:")
        for fname, desc in missing:
            if fname == "mame.xml":
                log.info("• Download the MAME XML from https://www.mamedev.org/release.php")
                log.info("• Extract the file from the mameXXXXlx.zip archive")
                log.info("• Rename it to 'mame.xml' and move it to the 'data' folder")
            elif fname == "history.xml":
                log.info("• Download the Gaming-History ZIP archive from:")
                log.info("  https://www.arcade-history.com/index.php?page=download")
                log.info("• Extract 'history.xml' from the 'history' subfolder inside the ZIP")
                log.info("• Move it to the 'data' folder")
            elif fname.startswith("[GAMING HISTORY]"):
                log.info(f"• Extract '{fname}' from the 'folders' subfolder inside the Gaming-History ZIP")
                log.info("• Move it to the 'data' folder, alongside history.xml")

        return False

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
        return "Unknown"


def main():
    """
    Entry point for the TM470 XML parsing pipeline.
    """
    log.info("Starting TM470 XML parsing pipeline...")

    if not check_required_files():
        log.error("Aborting. Required files missing.")
        return

    # Define file paths
    mame_file = Path("data/mame.xml")
    history_file = Path("data/history.xml")
    ini_game = Path("data/[GAMING HISTORY] Game Or No Game.ini")
    ini_category = Path("data/[GAMING HISTORY] Machine Category.ini")
    ini_type = Path("data/[GAMING HISTORY] Machine Type.ini")

    all_files = [mame_file, history_file, ini_game, ini_category, ini_type]

    # Detect encodings
    encodings = load_or_create_encodings(all_files)

    log.info(f"MAME XML encoding:                 {encodings.get('mame.xml', 'Unknown')}")
    log.info(f"History XML encoding:              {encodings.get('history.xml', 'Unknown')}")
    log.info(f"INI: Game Or No Game encoding:     {encodings.get('[GAMING HISTORY] Game Or No Game.ini', 'Unknown')}")
    log.info(f"INI: Machine Category encoding:    {encodings.get('[GAMING HISTORY] Machine Category.ini', 'Unknown')}")
    log.info(f"INI: Machine Type encoding:        {encodings.get('[GAMING HISTORY] Machine Type.ini', 'Unknown')}")

    # Fail if any .ini encoding is unknown
    for fname in [
        "[GAMING HISTORY] Game Or No Game.ini",
        "[GAMING HISTORY] Machine Category.ini",
        "[GAMING HISTORY] Machine Type.ini"
    ]:
        if encodings.get(fname) == "Unknown":
            log.error(f"Encoding detection failed for {fname}. Please ensure the file is valid.")
            return

    # Extract version metadata from both XML files
    mame_version_raw = get_xml_version(mame_file, "mame")
    history_version_raw = get_xml_version(history_file, "history")

    log.info(f"MAME XML version:      {mame_version_raw}")
    log.info(f"History XML version:   {history_version_raw}")

    mame_version = normalise_version(mame_version_raw)
    history_version = normalise_version(history_version_raw)

    log.info(f"Normalised MAME version:    {mame_version}")
    log.info(f"Normalised History version: {history_version}")

    if mame_version != history_version:
        log.warning("Version mismatch detected – MAME and Gaming-History XML versions do not match.")

    log.info("All checks passed. Ready to begin parsing.")

    # Parse MAME XML (0 = no record limit)
    machines = parse_mame_xml(mame_file, max_records=0)

    # Future: parse_history_xml()
    # Future: transform_data()
    # Future: write_output()


if __name__ == "__main__":
    main()
