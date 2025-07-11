from pathlib import Path
import xml.etree.ElementTree as ET
import re

from encoding_utils import load_or_create_encodings
from mame_parser import parse_mame_xml
from history_metadata import summarise_ini_classifications
from logger import setup_logger

log = setup_logger()


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
            log.info(f"Found file: data/{fname}")

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

    Validates file presence, detects encodings, extracts version info,
    logs .ini classification summaries, and parses MAME XML machines.
    """
    log.info("Starting TM470 XML parsing pipeline...")

    if not check_required_files():
        log.error("Aborting. Required files missing.")
        return

    # Define file paths
    data_dir = Path("data")
    mame_file = data_dir / "mame.xml"
    history_file = data_dir / "history.xml"
    xml_files = [mame_file, history_file]

    # Load or detect encodings
    encodings = load_or_create_encodings(xml_files + list(data_dir.glob("*.ini")))

    log.info(f"MAME XML encoding:                 {encodings.get('mame.xml', 'Unknown')}")
    log.info(f"History XML encoding:              {encodings.get('history.xml', 'Unknown')}")
    log.info(f"INI: Game Or No Game encoding:     {encodings.get('[GAMING HISTORY] Game Or No Game.ini', 'Unknown')}")
    log.info(f"INI: Machine Category encoding:    {encodings.get('[GAMING HISTORY] Machine Category.ini', 'Unknown')}")
    log.info(f"INI: Machine Type encoding:        {encodings.get('[GAMING HISTORY] Machine Type.ini', 'Unknown')}")

    # Extract and compare versions
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

    # Show classification summary from .ini files
    summary = summarise_ini_classifications()
    log.info("INI Classification Summary:")
    for category, counts in summary.items():
        log.info(f"--- {category} ---")
        for label, count in sorted(counts.items()):
            log.info(f"{label}: {count}")

    log.info("All checks passed. Ready to begin parsing.")

    # Parse MAME XML (includes clone-aware filtering)
    machines = parse_mame_xml(mame_file, max_records=0)

    log.info(f"Final machine count after clone-aware filtering: {len(machines)}")


if __name__ == "__main__":
    main()
