"""
Filename: history_parser.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Parses the Gaming-History XML file and provides structured metadata per <system> entry.
Counts all <entry> elements, differentiates between <systems> and <software>, extracts GH IDs,
aliases, and initial metadata placeholders. Also outputs debug information for puckman and pacman.

This file is part of a student project and is not intended for commercial use.
"""

from pathlib import Path
import xml.etree.ElementTree as ET
import time
import re
from collections import Counter

from config import LOG_LEVEL
from logger import setup_logger, debug_log

log = setup_logger(log_level=LOG_LEVEL)

def extract_gh_id(text: str) -> int | None:
    """
    Extracts the Gaming-History ID from a CONTRIBUTE link.
    """
    match = re.search(r'id=(\d+)', text)
    return int(match.group(1)) if match else None

def parse_history_entries(file_path: Path, encoding: str) -> dict[str, dict]:
    """
    Parses <entry> blocks in history.xml and returns structured GH metadata.

    Args:
        file_path (Path): Path to history.xml
        encoding (str): Encoding to use for reading the file

    Returns:
        dict[str, dict]: Structured GH metadata per primary <system>
    """
    log.info(f"Parsing history.xml entries from: {file_path.name} using {encoding}")

    total_entries = 0
    systems_count = 0
    software_count = 0
    headings_counter = Counter()
    result = {}
    heading_pattern = re.compile(r"^\s*-\s*([A-Z0-9 &]+?)\s*-\s*$")

    start = time.perf_counter()

    try:
        with open(file_path, encoding=encoding) as f:
            for event, elem in ET.iterparse(f, events=("end",)):
                if elem.tag == "entry":
                    total_entries += 1
                    has_systems = False
                    text_elem = elem.find("text")
                    text_content = text_elem.text if text_elem is not None else ""

                    for child in elem:
                        if child.tag == "systems":
                            has_systems = True
                            systems_count += 1
                        elif child.tag == "software":
                            software_count += 1

                    if has_systems:
                        systems_elem = elem.find("systems")
                        system_tags = systems_elem.findall("system") if systems_elem is not None else []
                        if not system_tags:
                            elem.clear()
                            continue

                        first_name = system_tags[0].attrib.get("name")
                        aliases = [s.attrib.get("name") for s in system_tags[1:]]
                        gh_id = extract_gh_id(text_content or "")

                        result[first_name] = {
                            "gh_id": gh_id,
                            "is_primary": True,
                            "aliases": aliases,
                            "sections": {
                                "Overview": "",
                            }
                        }

                        # Debug permanent for puckman and pacman
                        if first_name in {"puckman", "pacman"} or any(a in {"puckman", "pacman"} for a in aliases):
                            log.debug(f"[history_parser::parse_history_entries] {first_name}:")
                            log.debug(f"  GH ID: {gh_id}")
                            log.debug(f"  Aliases: {aliases}")

                        # Scan for headings
                        if text_content:
                            for line in text_content.splitlines():
                                match = heading_pattern.match(line)
                                if match:
                                    heading = match.group(1).strip().upper()
                                    headings_counter[heading] += 1

                    elem.clear()

    except ET.ParseError as e:
        log.error(f"XML parse error in {file_path.name}: {e}")
    except Exception as e:
        log.error(f"Unexpected error while parsing {file_path.name}: {e}")

    log.info(f"Parsed {total_entries} <entry> elements from history.xml")
    log.info(f"  - {systems_count} entries had <systems> (arcade-relevant)")
    log.info(f"  - {software_count} entries had <software> (non-arcade)")

    log.debug(f"[history_parser::parse_history_entries] Found {len(headings_counter)} unique headings across {systems_count} system entries.")
    for heading, count in sorted(headings_counter.items(), key=lambda x: (-x[1], x[0])):
        log.debug(f"  - {heading}: {count}")

    log.info(f"history.xml parsing completed in {time.perf_counter() - start:.2f} seconds")
    return result
