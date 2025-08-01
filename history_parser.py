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
from date_utils import parse_date_string


log = setup_logger(log_level=LOG_LEVEL)

# Global variables
unique_platforms = set()
unparsable_dates = {}  # {system_name: [bad date strings]}
#systems_with_residue = []  # List of system names where residue was detected
systems_with_residue = set()


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

def extract_ports_section(lines: list[str], system_name: str) -> tuple[str, Counter, dict]:
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
    global systems_with_residue

    overview_lines = []
    platform_counter = Counter()
    platform_entries = {}
    current_platform = None
    known_platforms = {"CONSOLES", "COMPUTERS", "HANDHELDS", "OTHERS"}
    found_first_platform = False
    total_port_lines = 0

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
            parsed_entry = parse_port_entry(line, system_name=system_name)
            platform_entries[current_platform].append(parsed_entry)
            total_port_lines += 1
            # Track if this port had residue
            if parsed_entry["residue"]:
                systems_with_residue.add(system_name)

    overview = " ".join(overview_lines).strip() if overview_lines else ""
    return overview, platform_counter, platform_entries, total_port_lines

   

def parse_port_entry(line: str, system_name: str = "") -> dict:
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
              - date (str)
              - publisher (str)
              - comment (str)
              - additional_tags (list[str])
              - residue (list[str])
    """
    port = {
        "regions": [],
        "platform": None,
        "model": None,
        "title": None,
        "date": None,
        "publisher": None,
        "comment": None,
        "additional_tags": [],
        "residue": []
    }

    global unparsable_dates
    original_line = line.strip()
    working_line = original_line
    port["residue"] = []

    # 1. Extract comment (everything after the first colon, unless inside quotes)
    original_line = line.strip()
    working_line = original_line
    comment_index = -1
    in_quotes = False

    for i, char in enumerate(working_line):
        if char == '"':
            in_quotes = not in_quotes
        elif char == ':' and not in_quotes:
            comment_index = i
            break

    if comment_index != -1:
        port["comment"] = working_line[comment_index + 1:].strip()
        working_line = working_line[:comment_index].strip()

    # 2. Extract square bracketed tags
    square_brackets = re.findall(r"\[(.*?)\]", working_line)
    for tag in square_brackets:
        tag_clean = tag.strip()
        if tag_clean.startswith("Model"):
            port["model"] = tag_clean.replace("Model", "").strip()
        elif len(tag_clean) == 2:
            port["regions"].append(tag_clean)
        else:
            port["additional_tags"].append(tag_clean)
        working_line = working_line.replace(f"[{tag}]", "")

    # 3. Extract quoted title
    match_title = re.search(r'"(.*?)"', working_line)
    if match_title:
        port["title"] = match_title.group(1).strip()
        working_line = working_line.replace(match_title.group(0), "")

    # Step 4: Extract date in parentheses
    match_date = re.search(r"\((.*?)\)", working_line)
    if match_date:
        date_raw = match_date.group(1).strip()
        normalised_date = parse_date_string(date_raw, context=system_name)

        if normalised_date:
            port["date"] = normalised_date
        else:
            port["residue"].append(date_raw)
            unparsable_dates.setdefault(system_name, []).append(date_raw)

        # Remove from working line regardless of validity
        working_line = working_line.replace(match_date.group(0), "").strip()


    # 5. Extract publisher (by XYZ)
    match_pub = re.search(r"\bby\s+(.+)", working_line)
    if match_pub:
        port["publisher"] = match_pub.group(1).strip()
        working_line = working_line[:match_pub.start()].strip()

    # 6. Remaining content assumed to be platform
    platform_candidate = working_line.strip()
    if platform_candidate:
        port["platform"] = platform_candidate
        global unique_platforms
        unique_platforms.add(platform_candidate)
        working_line = working_line.replace(platform_candidate, "", 1)

    # Step 7: Always include residue field
    #port.setdefault("residue", [])

    return port

   
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
    
    global unique_platforms
    unique_platforms.clear()
    
    total_entries = 0
    systems_count = 0
    software_count = 0
    port_overview_count = 0
    platform_totals = Counter()
    gh_entries = {}
    residue_count = 0
    systems_with_ports = 0
    systems_with_aliases = 0
    unique_platforms = set()
    total_port_lines_all = 0

    try:
        with open(file_path, encoding=encoding) as f:
            for event, elem in ET.iterparse(f, events=("end",)):
                if elem.tag != "entry":
                    continue

                total_entries += 1
                #entry_data = {}
                
                entry_data = {
                    "gh_id": None,
                    "aliases": [],
                    "port_overview": "",
                    "ports": {}
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
                            systems_with_aliases += 1
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
                        systems_with_ports += 1
                        #overview, platform_counts, platform_ports = extract_ports_section(sectioned["PORTS"], primary)
                        #overview, platform_counts, platform_ports, total_port_lines = extract_ports_section(sectioned["PORTS"], primary)
                        overview, platform_counts, platform_ports, port_lines = extract_ports_section(sectioned["PORTS"], primary)
                        total_port_lines_all += port_lines
                        
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


    # After all parsing is done
    parsing_summary = {
        "systems_total": systems_count,
        "systems_with_ports": systems_with_ports,
        "systems_with_aliases": systems_with_aliases,
        "port_lines_parsed": total_port_lines_all,
        "invalid_dates": {
            "count": len(unparsable_dates),
            "examples": unparsable_dates  # Dict[str, List[str]]
        },
        "systems_with_residue": {
            "count": len(systems_with_residue),
            "examples": sorted(list(systems_with_residue))
        },
        "unique_platforms": {
            "count": len(unique_platforms),
            "examples": sorted(unique_platforms)  # Sorted list
        }
    }

    summary_path = Path("data/history_parsing_summary.json")
    try:
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(parsing_summary, f, indent=2)
        debug_log(f"Wrote parsing summary to {summary_path}")
    except Exception as e:
        log.warning(f"Could not write parsing summary: {e}")


    log.info(f"History parsing completed in {time.perf_counter():.2f} seconds")    
    return gh_entries
