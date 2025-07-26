"""
Filename: history_parser.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Parses the Gaming-History XML file and provides a summary count of all <entry> elements,
distinguishing between those with <systems> (arcade-relevant) and <software> (home/non-arcade).

This file is part of a student project and is not intended for commercial use.
"""

from pathlib import Path
import xml.etree.ElementTree as ET
import time

from config import LOG_LEVEL
from logger import setup_logger, debug_log

log = setup_logger(log_level=LOG_LEVEL)

def parse_history_xml(file_path: Path, encoding: str) -> None:
    """
    Parses the Gaming-History XML file and counts <entry> types.

    Args:
        file_path (Path): Path to history.xml
        encoding (str): Detected encoding for history.xml (from encodings.json)
    """
    start = time.perf_counter()
    log.info(f"Starting history.xml parsing: {file_path.name} using {encoding}")

    total_entries = 0
    systems_count = 0
    software_count = 0

    try:
        with open(file_path, encoding=encoding) as f:
            for event, elem in ET.iterparse(f, events=("end",)):
                if elem.tag == "entry":
                    total_entries += 1
                    for child in elem:
                        if child.tag == "systems":
                            systems_count += 1
                        elif child.tag == "software":
                            software_count += 1
                    elem.clear()
    except ET.ParseError as e:
        log.error(f"XML parse error in {file_path.name}: {e}")
        return

    log.info(f"Parsed {total_entries} <entry> elements from history.xml")
    log.info(f"  - {systems_count} entries had <systems> (arcade-relevant)")
    log.info(f"  - {software_count} entries had <software> (non-arcade)")
    log.info(f"History parsing completed in {time.perf_counter() - start:.2f} seconds")
