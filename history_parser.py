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
from collections import Counter, defaultdict, OrderedDict

from config import LOG_LEVEL
from logger import setup_logger, debug_log
from date_utils import parse_date_string

log = setup_logger(log_level=LOG_LEVEL)

# Updated pattern: match lines that start with '- ', end with ' -', and have something in between
#SECTION_PATTERN = re.compile(r"^- .+? -$")
SECTION_PATTERN = re.compile(r"^-+\s+([A-Z0-9 &]+)\s+-+$", re.IGNORECASE)
CATEGORY_HEADING_PATTERN = re.compile(r"^\*\s*([A-Z0-9 &]+)\s*:\s*$", re.IGNORECASE)
KNOWN_PLATFORMS = {"CONSOLES", "COMPUTERS", "HANDHELDS", "OTHERS"}

# Simple function to advise if a number is odd or not.
def is_odd(n):
    return n % 2 == 1


def segment_text_sections(text: str, parsing_state: dict) -> dict:
    sections = defaultdict(list)
    current_section = "OVERVIEW"

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        match = SECTION_PATTERN.match(line)
        if match:
            section_name = match.group(1).strip().upper()
            current_section = section_name
            parsing_state.setdefault("section_headings_found", Counter())[section_name] += 1
        else:
            sections[current_section].append(line)

    return sections

def extract_ports_section(lines: list[str], system_name: str, parsing_state: dict) -> tuple[str, Counter, dict, int]:
    overview_lines = []
    platform_counter = Counter()
    platform_entries = {}
    current_platform = None
    found_first_platform = False
    total_port_lines = 0

    for line in lines:
        line = line.strip()

        match = CATEGORY_HEADING_PATTERN.match(line)
        if match:
            category_name = match.group(1).strip()
            category_upper = category_name.upper()

            parsing_state.setdefault("platform_categories_found", Counter())[category_name] += 1

            if category_upper in KNOWN_PLATFORMS:
                platform_counter[category_upper] += 1
                platform_entries.setdefault(category_upper, [])
                current_platform = category_upper
                found_first_platform = True
            else:
                parsing_state.setdefault("unexpected_platform_categories", defaultdict(list))[category_name].append(system_name)
                current_platform = None
            continue

        if not found_first_platform:
            if line:
                overview_lines.append(line)
            continue

        if current_platform and line:
            parsed_entry = parse_port_entry(line, system_name=system_name, parsing_state=parsing_state)
            platform_entries[current_platform].append(parsed_entry)
            total_port_lines += 1
            if parsed_entry["residue"]:
                parsing_state.setdefault("systems_with_residue", set()).add(system_name)

    overview = " ".join(overview_lines).strip() if overview_lines else ""
    return overview, platform_counter, platform_entries, total_port_lines
    
    
def parse_port_entry(line: str, system_name: str = "", parsing_state: dict = None) -> dict:
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

    original_line = line.strip()
    working_line = original_line
    
    # Count quote characters, ignoring valid floppy disk sizes like 3.5" and 5.25"
    disk_quote_matches = re.findall(r'\b(?:3\.5|5\.25)"(?!\w)', working_line)
    quote_count = working_line.count('"') - len(disk_quote_matches)

    # Count all bracket types
    bracket_count = (
        working_line.count('(') + working_line.count(')') +
        working_line.count('[') + working_line.count(']') +
        working_line.count('{') + working_line.count('}')
    )

    if is_odd(quote_count):
        parsing_state.setdefault("odd_quotes", defaultdict(list))[system_name].append(working_line)

    if is_odd(bracket_count):
        parsing_state.setdefault("odd_brackets", defaultdict(list))[system_name].append(working_line)

    # Step 1: Extract comment (everything after first colon not in quotes)
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

    # Step 2: Extract square bracketed tags
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

    # Step 3: Extract quoted title
    match_title = re.search(r'"(.*?)"', working_line)
    if match_title:
        port["title"] = match_title.group(1).strip()
        working_line = working_line.replace(match_title.group(0), "")

    # Step 4 & 5: Extract date and publisher
    match_date = re.search(r"\((.*?)\)", working_line)
    if match_date:
        date_raw = match_date.group(1).strip()
        normalised_date = parse_date_string(date_raw, context=system_name)

        if normalised_date:
            port["date"] = normalised_date
        else:
            port["residue"].append(date_raw)
            parsing_state.setdefault("unparsable_dates", defaultdict(list))[system_name].append(date_raw)

        # Use date as delimiter: publisher is whatever comes after it
        post_date_text = working_line[match_date.end():].strip()
        if post_date_text:
            cleaned_pub = re.sub(r"^\s*by\s+", "", post_date_text, flags=re.IGNORECASE).strip()
            cleaned_pub = re.sub(r"^\s*-\s*", "", cleaned_pub)
            cleaned_pub = cleaned_pub.rstrip(".:; ")
            port["publisher"] = cleaned_pub
            publisher_data = parsing_state["publishers_found"][cleaned_pub]
            publisher_data["count"] += 1
            publisher_data["systems"].append(system_name)
        working_line = working_line[:match_date.start()].strip()
    else:
        match_pub = re.search(r"\bby\s+(.+)", working_line)
        if match_pub:
            cleaned_pub = match_pub.group(1).strip()
            cleaned_pub = re.sub(r"^\s*-\s*", "", cleaned_pub)
            cleaned_pub = cleaned_pub.rstrip(".:; ")
            port["publisher"] = cleaned_pub
            publisher_data = parsing_state["publishers_found"][cleaned_pub]
            publisher_data["count"] += 1
            publisher_data["systems"].append(system_name)
            working_line = working_line[:match_pub.start()].strip()

    # Step 6: Assign remaining as platform
    platform_candidate = working_line.strip()
    if platform_candidate:
        port["platform"] = platform_candidate
        parsing_state.setdefault("platforms_found", Counter())[platform_candidate] += 1

    return port


def parse_history_entries(file_path: Path, encoding: str) -> dict:
    start = time.perf_counter()
    log.info(f"Parsing history.xml entries from: {file_path.name} using {encoding}")

    parsing_state = {
        "platforms_found": Counter(),
        "unparsable_dates": defaultdict(list),
        "systems_with_residue": set(),
        "section_headings_found": Counter(),
        "platform_categories_found": Counter(),
        "unexpected_platform_categories": defaultdict(list),
        "publishers_found": defaultdict(lambda: {"count": 0, "systems": []}),
        "odd_quotes": defaultdict(list),
        "odd_brackets": defaultdict(list)
    }

    total_entries = 0
    systems_count = 0
    software_count = 0
    port_overview_count = 0
    platform_totals = Counter()
    gh_entries = {}
    residue_count = 0
    systems_with_ports = 0
    systems_with_aliases = 0
    total_port_lines_all = 0

    try:
        with open(file_path, encoding=encoding) as f:
            for event, elem in ET.iterparse(f, events=("end",)):
                if elem.tag != "entry":
                    continue

                total_entries += 1
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
                    sectioned = segment_text_sections(raw_text, parsing_state)

                    if primary in ("puckman", "pacman"):
                        debug_log(f"{primary}:")
                        debug_log(f"  GH ID: {entry_data.get('gh_id')}")
                        debug_log(f"  Aliases: {entry_data.get('aliases', [])}")
                        for section, lines in sectioned.items():
                            preview = " ".join(lines).strip().replace("\n", " ")[:40]
                            debug_log(f"  Section: {section} -> {preview}...")

                    if "CONTRIBUTE" in sectioned:
                        for line in sectioned["CONTRIBUTE"]:
                            match = re.search(r"id=(\d+)", line)
                            if match:
                                entry_data["gh_id"] = int(match.group(1))
                                break

                    if "PORTS" in sectioned:
                        systems_with_ports += 1
                        overview, platform_counts, platform_ports, port_lines = extract_ports_section(sectioned["PORTS"], primary, parsing_state)
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
    log.info(f"  - {port_overview_count} entries contained a port overview")

    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "gh_entries.json"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(gh_entries, f, indent=2, ensure_ascii=False)
        log.info(f"Saved parsed GH metadata to {output_file}")
    except Exception as e:
        log.error(f"Failed to write GH entries JSON: {e}")

    # Summary structure
    summary = {
        "totals": {
            "systems_total": systems_count,
            "systems_with_ports": systems_with_ports,
            "systems_with_aliases": systems_with_aliases,
            "port_lines_parsed": total_port_lines_all
        },
        "found": {
            "section_headings_found": dict(parsing_state["section_headings_found"]),
            "platform_categories_found": dict(parsing_state["platform_categories_found"]),
            "platforms_found": {
                "count": len(parsing_state["platforms_found"]),
                "examples": dict(sorted(parsing_state["platforms_found"].items()))
            },
            "publishers_found": {
                "count": len(parsing_state["publishers_found"]),
                "examples": dict(sorted(parsing_state["publishers_found"].items()))
            }
        },
        "anomalies": {
            "unexpected_platform_categories": {
                k: sorted(v) for k, v in sorted(parsing_state["unexpected_platform_categories"].items())
            },
            "odd_quotes": {
                k: v for k, v in sorted(parsing_state["odd_quotes"].items())
            },
            "odd_brackets": {
                k: v for k, v in sorted(parsing_state["odd_brackets"].items())
            }
        },
        "residue_flags": {
            "unparsable_dates": {
                "count": len(parsing_state["unparsable_dates"]),
                "examples": parsing_state["unparsable_dates"]
            },
            "systems_with_residue": {
                "count": len(parsing_state["systems_with_residue"]),
                "examples": sorted(parsing_state["systems_with_residue"])
            }
        }
    }

    summary_path = Path("data/history_parsing_summary.json")
    try:
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        debug_log(f"Wrote parsing summary to {summary_path}")
    except Exception as e:
        log.warning(f"Could not write parsing summary: {e}")

    log.info(f"History parsing completed in {time.perf_counter() - start:.2f} seconds")

    return gh_entries
