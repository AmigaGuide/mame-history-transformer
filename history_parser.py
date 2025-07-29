"""
Filename: history_parser.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Parses the Gaming-History XML file (history.xml) and extracts structured metadata from
<entry> elements, distinguishing between arcade-relevant <systems> and non-arcade <software>.

For arcade entries, the script captures:
- The primary GH system name and any aliases
- The Gaming-History ID (gh_id) from the CONTRIBUTE section
- Each <text> section is segmented before parsing
- A PORTS section is parsed for:
  - Overview paragraph
  - Platform category counters (CONSOLES, COMPUTERS, etc.)
  - A full list of parsed port entries with extracted metadata

Output is saved to output/gh_entries.json and used to support ExoticA's
Lost in Translation (LiT) Wiki metadata.

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

SECTION_PATTERN = re.compile(r"^-+\s*(.+?)\s*-+$")


def segment_text_sections(text: str) -> dict:
    """
    Segments the full <text> content from a <system> entry into named sections.

    Sections are identified by lines surrounded with dashes, e.g., '--- PORTS ---',
    and each subsequent line is grouped under the most recent heading until a new
    heading is found. If no heading is found before the first line, the content is
    assigned to an implicit "OVERVIEW" section.

    Args:
        text (str): The raw <text> content from a Gaming-History <system> entry.

    Returns:
        dict: A dictionary where keys are section names (uppercase) and values are
              lists of lines belonging to each section.
    """
    sections = defaultdict(list)
    current_section = "OVERVIEW"

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        match = SECTION_PATTERN.match(line)
        if match:
            section_name = match.group(1).upper()
            current_section = section_name
        else:
            sections[current_section].append(line)

    return sections


def extract_ports_section(lines: list[str]) -> tuple[str, Counter, dict]:
    """
    Parses the lines from the PORTS section of a <system> entry to extract structured data.

    This function identifies an optional overview paragraph, counts platform headings
    (e.g., CONSOLES, COMPUTERS), and parses individual port entries under each platform.
    The PORTS section is expected to be pre-isolated by segment_text_sections().

    Args:
        lines (list[str]): Lines belonging to the PORTS section, excluding headers.

    Returns:
        tuple:
            - str: An optional overview paragraph found before the first platform heading.
            - Counter: A tally of platform categories encountered (e.g., CONSOLES: 5).
            - dict: A dictionary mapping platform categories to lists of parsed port entries.
    """
    overview_lines = []
    platform_counter = Counter()
    platform_entries = {}
    current_platform = None
    known_platforms = {"CONSOLES", "COMPUTERS", "HANDHELDS", "OTHERS"}
    found_first_platform = False

    for line in lines:
        line = line.strip()
        if not found_first_platform:
            if re.fullmatch(r"\*[A-Z0-9 &]+:\s*", line):
                platform = line.strip("*:").strip().upper()
                if platform in known_platforms:
                    platform_counter[platform] += 1
                    platform_entries[platform] = []
                    current_platform = platform
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
                if platform not in platform_entries:
                    platform_entries[platform] = []
                current_platform = platform
            else:
                current_platform = None
            continue

        if current_platform and line:
            parsed_entry = parse_port_entry(line)
            platform_entries[current_platform].append(parsed_entry)

    overview = " ".join(overview_lines).strip() if overview_lines else ""
    return overview, platform_counter, platform_entries
   

def parse_port_entry(line: str) -> dict:
    """
    Parses a single port entry line into structured metadata fields.

    This function extracts various components from a free-text port entry, including:
    - Regions (e.g., [JP], [US])
    - Platform name
    - Model number (e.g., [Model ABC-123])
    - Year (inside parentheses, e.g., (1998) or (June.23, 2011))
    - Title (inside double quotes)
    - Publisher (after 'by')
    - Additional tags (other square bracketed values)
    - Inline comment (after colon ':')
    - Residue (any unmatched content after all known patterns are removed)

    Args:
        line (str): A single line representing a port entry under a platform heading.

    Returns:
        dict: A dictionary with the extracted metadata fields. Keys include:
              - regions (list[str])
              - platform (str)
              - model (str)
              - title (str)
              - year (str)
              - publisher (str)
              - comment (str)
              - additional_tags (list[str])
              - residue (str)
    """
    entry = {
        "regions": [],
        "platform": None,
        "model": None,
        "title": None,
        "year": None,
        "publisher": None,
        "comment": None,
        "additional_tags": [],
        "residue": None
    }

    original_line = line.strip()
    working_line = original_line

    # 1. Extract comment (everything after the first colon)
    if ":" in working_line:
        main_part, comment = working_line.split(":", 1)
        entry["comment"] = comment.strip()
        working_line = main_part.strip()

    # 2. Extract square bracketed tags
    square_brackets = re.findall(r"\[(.*?)\]", working_line)
    for tag in square_brackets:
        tag_clean = tag.strip()
        if tag_clean.startswith("Model"):
            entry["model"] = tag_clean.replace("Model", "").strip()
        elif len(tag_clean) == 2:
            entry["regions"].append(tag_clean)
        else:
            entry["additional_tags"].append(tag_clean)
        working_line = working_line.replace(f"[{tag}]", "")

    # 3. Extract quoted title
    match_title = re.search(r'"(.*?)"', working_line)
    if match_title:
        entry["title"] = match_title.group(1).strip()
        working_line = working_line.replace(match_title.group(0), "")

    # 4. Extract year in parentheses
    match_year = re.search(r"\((.*?)\)", working_line)
    if match_year:
        entry["year"] = match_year.group(1).strip()
        working_line = working_line.replace(match_year.group(0), "")

    # 5. Extract publisher (by XYZ)
    match_pub = re.search(r"\bby\s+(.+)", working_line)
    if match_pub:
        entry["publisher"] = match_pub.group(1).strip()
        working_line = working_line[:match_pub.start()].strip()

    # 6. Remaining content assumed to be platform
    platform_candidate = working_line.strip()
    if platform_candidate:
        entry["platform"] = platform_candidate
        working_line = working_line.replace(platform_candidate, "", 1)

    # 7. Any leftover content is residue
    residue = working_line.strip()
    if residue:
        entry["residue"] = residue

    return entry

   
def parse_history_entries(file_path: Path, encoding: str) -> dict:
    """
    Parses the Gaming-History XML file and extracts structured metadata from <entry> elements.

    This function focuses on <systems> entries (arcade-relevant) and ignores <software> entries.
    It processes each <text> field by segmenting it into named sections and extracting:
    - The Gaming-History ID (gh_id) from the CONTRIBUTE section
    - An optional list of aliases (from additional <system> names)
    - A PORTS section, which is further analysed into:
        • A free-text overview paragraph
        • Platform category counters (e.g., CONSOLES, COMPUTERS)
        • Structured port entries (one per line under each platform heading)

    The resulting metadata is saved to output/gh_entries.json and returned as a dictionary.

    Args:
        file_path (Path): Path to the Gaming-History XML file (typically history.xml).
        encoding (str): Detected character encoding for correct file reading.

    Returns:
        dict: A dictionary keyed by primary <system> name, with values containing:
              - gh_id (int)
              - aliases (list[str], optional)
              - port_overview (str, optional)
              - ports (dict[str, list[dict]], optional)
    """
    log.info(f"Parsing history.xml entries from: {file_path.name} using {encoding}")
    total_entries = 0
    systems_count = 0
    software_count = 0
    port_overview_count = 0
    platform_totals = Counter()
    gh_entries = {}
    residue_count = 0

    try:
        with open(file_path, encoding=encoding) as f:
            for event, elem in ET.iterparse(f, events=("end",)):
                if elem.tag != "entry":
                    continue

                total_entries += 1
                entry_data = {}

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
                    sectioned = segment_text_sections(raw_text)

                    if primary in ("puckman", "pacman"):
                        debug_log(f"{primary}:")
                        debug_log(f"  GH ID: {entry_data.get('gh_id')}")
                        debug_log(f"  Aliases: {entry_data.get('aliases', [])}")
                        for section, lines in sectioned.items():
                            preview = " ".join(lines).strip().replace("\n", " ")[:40]
                            debug_log(f"  Section: {section} -> {preview}...")

                    # Extract GH ID from CONTRIBUTE section (if not already handled)
                    if "CONTRIBUTE" in sectioned:
                        for line in sectioned["CONTRIBUTE"]:
                            match = re.search(r"id=(\d+)", line)
                            if match:
                                entry_data["gh_id"] = int(match.group(1))
                                break

                    if "PORTS" in sectioned:
                        overview, platform_counts, platform_ports = extract_ports_section(sectioned["PORTS"])
                        for entries in platform_ports.values():
                            for entry in entries:
                                if entry.get("residue"):
                                    residue_count += 1
                        if overview:
                            entry_data["port_overview"] = overview
                            port_overview_count += 1
                        if platform_ports:
                            entry_data["ports"] = platform_ports
                        platform_totals.update(platform_counts)

                gh_entries[primary] = entry_data

                elem.clear()

    except ET.ParseError as e:
        log.error(f"XML parse error in {file_path.name}: {e}")
        return {}

    log.info(f"Parsed {total_entries} <entry> elements from history.xml")
    log.info(f"  - {systems_count} entries had <systems> (arcade-relevant)")
    log.info(f"  - {software_count} entries had <software> (non-arcade)")
    log.debug(f"Unique PORTS platform categories found: {len(platform_totals)}")
    for platform, count in sorted(platform_totals.items(), key=lambda x: (-x[1], x[0])):
        log.debug(f"  - {platform}: {count}")
    log.info(f"  - {port_overview_count} entries contained a port overview")

    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "gh_entries.json"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(gh_entries, f, indent=2)
        log.info(f"Saved parsed GH metadata to output/gh_entries.json")
    except Exception as e:
        log.error(f"Failed to write GH entries JSON: {e}")

    log.info(f"  - {residue_count} port entries contained residue after parsing")

    log.info(f"History parsing completed in {time.perf_counter():.2f} seconds")
    return gh_entries
