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
import re
import json
import html
from collections import Counter, defaultdict

from config import LOG_LEVEL
from logger import setup_logger, debug_log

log = setup_logger(log_level=LOG_LEVEL)

def parse_ports(text_block: str) -> tuple[str, Counter]:
    """
    Extracts an optional overview and platform categories from a PORTS section.

    Args:
        text_block (str): Full <text> content from a <system> entry.

    Returns:
        tuple[str, Counter]: Tuple of optional overview string and Counter of platform categories.
    """
    lines = text_block.splitlines()
    in_ports_section = False
    overview_lines = []
    platform_counter = Counter()
    found_first_platform = False

    known_platforms = {"CONSOLES", "COMPUTERS", "HANDHELDS", "OTHERS"}

    for line in lines:
        line = line.strip()

        if not in_ports_section:
            if re.fullmatch(r"-+\s*PORTS\s*-+", line.upper()):
                in_ports_section = True
            continue

        if not found_first_platform:
            if re.fullmatch(r"\*[A-Z0-9 &]+:\s*", line):
                platform = line.strip("*:").strip().upper()
                if platform in known_platforms:
                    platform_counter[platform] += 1
                    found_first_platform = True
                else:
                    overview_lines.append(line)
            elif line:
                overview_lines.append(line)
            continue

        if re.fullmatch(r"\*[A-Z0-9 &]+:\s*", line):
            platform = line.strip("*:").strip().upper()
            if platform in known_platforms:
                platform_counter[platform] += 1

    overview = " ".join(overview_lines).strip() if overview_lines else ""
    return overview, platform_counter

def parse_history_entries(file_path: Path, encoding: str) -> dict:
    """
    Parses the Gaming-History XML file and extracts relevant data from <systems> entries.
    Stores primary system name, GH ID from CONTRIBUTE section, aliases, and PORTS summary.

    Args:
        file_path (Path): Path to history.xml
        encoding (str): Detected encoding for history.xml (from encodings.json)

    Returns:
        dict: Dictionary of system entries with GH metadata.
    """
    log.info(f"Parsing history.xml entries from: {file_path.name} using {encoding}")

    total_entries = 0
    systems_count = 0
    software_count = 0
    port_overview_count = 0
    platform_totals = Counter()
    gh_entries = {}

    try:
        with open(file_path, encoding=encoding) as f:
            for event, elem in ET.iterparse(f, events=("end",)):
                if elem.tag != "entry":
                    continue

                total_entries += 1
                entry_data = {
                    "gh_id": None,
                }

                systems_elem = elem.find("systems")
                software_elem = elem.find("software")

                if systems_elem is not None:
                    systems_count += 1
                    system_names = [s.attrib.get("name") for s in systems_elem.findall("system") if s.attrib.get("name")]

                    if system_names:
                        primary = system_names[0]
                        aliases = system_names[1:]
                        if aliases:
                            entry_data["aliases"] = aliases
                    else:
                        elem.clear()
                        continue
                elif software_elem is not None:
                    software_count += 1
                    elem.clear()
                    continue
                else:
                    elem.clear()
                    continue

                text_elem = elem.find("text")
                if text_elem is not None and text_elem.text:
                    raw_text = html.unescape(text_elem.text)
                    match = re.search(r"id=(\d+)", raw_text)
                    if match:
                        entry_data["gh_id"] = int(match.group(1))

                    overview, platform_counts = parse_ports(raw_text)
                    if overview:
                        entry_data["port_overview"] = overview
                        port_overview_count += 1
                    platform_totals.update(platform_counts)

                gh_entries[primary] = entry_data

                if primary in ("puckman", "pacman"):
                    debug_log(f"[history_parser::parse_history_entries] {primary}:")
                    debug_log(f"  GH ID: {entry_data['gh_id']}")
                    debug_log(f"  Aliases: {entry_data['aliases']}")

                elem.clear()

    except ET.ParseError as e:
        log.error(f"XML parse error in {file_path.name}: {e}")
        return {}

    log.info(f"Parsed {total_entries} <entry> elements from history.xml")
    log.info(f"  - {systems_count} entries had <systems> (arcade-relevant)")
    log.info(f"  - {software_count} entries had <software> (non-arcade)")
    log.debug(f"[history_parser::parse_history_entries] Unique PORTS platform categories found: {len(platform_totals)}")
    for platform, count in sorted(platform_totals.items(), key=lambda x: (-x[1], x[0])):
        log.debug(f"  - {platform}: {count}")
    log.info(f"  - {port_overview_count} entries contained a port overview")

    count = 0
    for name, data in gh_entries.items():
        if data.get("port_overview"):
            debug_log(f"[history_parser::parse_history_entries] Port overview for {name}: {data['port_overview'][:100]}...")
            count += 1
            if count >= 10:
                break

    # Write gh_entries.json
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "gh_entries.json"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(gh_entries, f, indent=2)
        log.info(f"Saved parsed GH metadata to {output_file}")
    except Exception as e:
        log.error(f"Failed to write GH entries JSON: {e}")

    log.info(f"History parsing completed in {time.perf_counter():.2f} seconds")
    return gh_entries
