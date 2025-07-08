from pathlib import Path
import xml.etree.ElementTree as ET
import re

from encoding_utils import load_or_create_encodings
from mame_parser import parse_mame_xml
from logger import setup_logger

log = setup_logger()


def check_required_files() -> bool:
    """
    Check for the presence of required XML files in the 'data' folder.

    Returns:
        bool: True if both mame.xml and history.xml are found, False otherwise.
    """
    data_dir = Path("data")
    mame_file = data_dir / "mame.xml"
    history_file = data_dir / "history.xml"

    missing = []

    if not mame_file.is_file():
        missing.append("mame.xml")
    else:
        log.info("Found file: data/mame.xml")

    if not history_file.is_file():
        missing.append("history.xml")
    else:
        log.info("Found file: data/history.xml")

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

    - If version starts with '0.', remove any trailing bracketed info.
    - If version is like '2.78', convert to float and divide by 10.
    - If parsing fails, return 'Unknown'.

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

    Checks file presence, loads cached or detected encodings, and reports
    version metadata for both MAME and Gaming-History XML files.
    """
    log.info("Starting TM470 XML parsing pipeline...")

    if not check_required_files():
        log.error("Aborting. Required files missing.")
        return

    # Define file paths
    mame_file = Path("data/mame.xml")
    history_file = Path("data/history.xml")
    xml_files = [mame_file, history_file]

    # Load or detect encodings
    encodings = load_or_create_encodings(xml_files)
    mame_encoding = encodings.get("mame.xml", "Unknown")
    history_encoding = encodings.get("history.xml", "Unknown")

    log.info(f"MAME XML encoding:     {mame_encoding}")
    log.info(f"History XML encoding:  {history_encoding}")

    # Extract raw version info
    mame_version_raw = get_xml_version(mame_file, "mame")
    history_version_raw = get_xml_version(history_file, "history")

    log.info(f"MAME XML version:      {mame_version_raw}")
    log.info(f"History XML version:   {history_version_raw}")

    # Normalise for comparison
    mame_version = normalise_version(mame_version_raw)
    history_version = normalise_version(history_version_raw)

    log.info(f"Normalised MAME version:    {mame_version}")
    log.info(f"Normalised History version: {history_version}")

    if mame_version != history_version:
        log.warning("Version mismatch detected – MAME and Gaming-History XML versions do not match.")

    log.info("All checks passed. Ready to begin parsing.")

    # Parse MAME XML (limited to 1000 records during development)
    #machines = parse_mame_xml(mame_file, max_records=1000)
    machines = parse_mame_xml(mame_file, max_records=0)  # 0 = no limit


    if machines:
        log.info(f"First parsed machine: {machines[0]}")
    else:
        log.warning("No machines were parsed from mame.xml.")

    # Future calls:
    # parse_history_xml()
    # transform_data()
    # write_output()


if __name__ == "__main__":
    main()
