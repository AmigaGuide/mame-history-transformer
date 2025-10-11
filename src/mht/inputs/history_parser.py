"""
Filename: history_parser.py
Author: XtC

Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Purpose:
Stream-parse Gaming-History's history.xml <entry> elements and extract structured,
arcade-relevant metadata for ExoticA's LiT. Handles section segmentation, PORTS
parsing (including platform banners and inheritance), and emits a rich summary.

Inputs:
- history.xml (Gaming-History export), encoding determined externally and passed in.
- Optional: CONTRIBUTE section lines containing gh_id (format: 'id=<int>').

Outputs:
- output/gh_system_ports.json (per-system structured PORTS data, sorted)
- data/history_parsing_summary.json (totals, distributions, anomalies, audits)
"""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET
import time
import re
import json
import html
from collections import Counter, defaultdict
import datetime

from mht.utils.config import LOG_LEVEL
from mht.utils.logger import setup_logger, debug_log, maybe_log_progress
from mht.utils.date_utils import parse_date_string
from mht.utils.versions import SCHEMA_IDS, schema_version, tool_version
from mht.utils.stamps import make_stamp, load_stamp, save_stamp, is_fresh
from mht.utils.paths import (
    STAMPS_DIR,
    GH_SYSTEM_PORTS_PATH,
    HISTORY_SUMMARY,
    ENCODINGS_JSON,
)
from mht.utils.headers import build_summary_header
from mht.utils.io import write_json, read_json
from mht.utils.ports import (
    is_valid_port_row as _is_valid_port_row,
    norm_regions      as _norm_regions,
    norm_tags         as _norm_tags,
)
from mht.inputs.history_constants import (
    CATEGORY_HEADING_PATTERN,
    KNOWN_PLATFORMS,
)
from mht.inputs.history_ports import (
    extract_ports_section,
)
from mht.inputs.history_text import segment_text_sections, parse_gh_id_from_contribute, extract_text_sections
from mht.inputs.history_summary import build_history_summary
from mht.utils.history_xml import (
    iter_history_events,
    capture_history_root_attrs,
    get_entry_header,
    get_entry_texts,
    classify_entry,
)
from mht.utils.validator import check_history_parse_invariants
from mht.utils.records import build_history_system_record, build_history_systems_sorted
from mht.utils.summaries import apply_ports_results


__all__ = [
    "parse_history_entries",
]

log = setup_logger(log_level=LOG_LEVEL)


def parse_history_entries(file_path: Path, encoding: str) -> bool:
    """
    Stream-parse history.xml <entry> elements and emit structured outputs.
    """
    start = time.perf_counter()
    log.info(f"Parsing history.xml entries from: {file_path.name} using {encoding}")

    # Read <history> root attributes for the summary header
    history_version, history_date = None, None

    # --- Stage stamp: skip unchanged ---
    STAMPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp_path = STAMPS_DIR / "history.json"
    current_stamp = make_stamp(
        schema_id="mht.stage.history",
        tool_version=tool_version("history_parser"),
        inputs=[file_path, ENCODINGS_JSON],
    )
    prev = load_stamp(stamp_path)
    if is_fresh(current_stamp, prev):
        log.info("History stage up-to-date (stamp matched) — skipping parse")
        return True

    parsing_state = {
        "platforms_found": defaultdict(lambda: {"count": 0, "systems": []}),
        "ports_with_comments": 0,
        "unparsable_dates": defaultdict(list),
        "systems_with_residue": set(),
        "section_headings_found": Counter(),
        "platform_categories_found": Counter(),
        "unexpected_platform_categories": defaultdict(list),
        "publishers_found": defaultdict(lambda: {"count": 0, "systems": []}),
        "publisher_indicators_found": {"released_by": 0, "by": 0, "other_after_date": 0, "none": 0},
        "odd_quotes": defaultdict(list),
        "odd_brackets": defaultdict(list),
        "titles_found": set(),
        "region_codes": Counter(),
        "models_found": defaultdict(list),
        "comments_found": defaultdict(list),
        "additional_tags_found": defaultdict(list),
        "systems_with_port_overview": {},
        "platform_banner_total": 0,
        "platform_banners_by_system": defaultdict(Counter),
        "null_platform_ports_total": 0,
        "null_platform_ports_by_system": Counter(),
        "null_platform_examples": defaultdict(list),
        "disk_size_quotes": defaultdict(list),
    }

    # Totals
    total_entries = 0
    systems_count = 0
    software_count = 0
    systems_with_ports = 0
    systems_with_aliases = 0
    port_overview_count = 0
    total_port_lines_all = 0

    gh_systems = {}

    # Streaming parse of history.xml
    try:
        for event, elem in iter_history_events(file_path, encoding):

            # Capture <history> root attributes on the start event (once)
            hdr = capture_history_root_attrs(event, elem)
            if hdr is not None:
                # Only set if not already captured
                if history_version is None:
                    history_version = hdr.get("version")
                if history_date is None:
                    history_date = hdr.get("date")
                # Continue the loop; entries are handled on 'end'
                continue

            # Process each <entry> at its end tag
            if event == "end" and elem.tag == "entry":
                total_entries += 1
                maybe_log_progress(
                    log,
                    total_entries,
                    step=10000,
                    prefix="[history_parser::parse_history_entries]",
                    fmt="{prefix} Parsed {count:,} entries so far...",
                )

                kind, primary, aliases = classify_entry(elem)

                if kind == "systems":
                    systems_count += 1
                    if not primary:
                        elem.clear()
                        continue
                    entry_data = build_history_system_record(aliases=aliases)
                    if aliases:
                        systems_with_aliases += 1

                elif kind == "software":
                    software_count += 1
                    elem.clear()
                    continue

                else:
                    elem.clear()
                    continue

                sectioned = extract_text_sections(elem, parsing_state)
                if sectioned:
                    if "CONTRIBUTE" in sectioned:
                        gh_id = parse_gh_id_from_contribute(sectioned["CONTRIBUTE"])
                        if gh_id is not None:
                            entry_data["gh_id"] = gh_id

                    if "PORTS" in sectioned:
                        overview, platform_counts, platform_ports, port_lines = extract_ports_section(
                            sectioned["PORTS"], primary, parsing_state
                        )
                        systems_with_ports, port_overview_count, total_port_lines_all, entry_data = apply_ports_results(
                            parsing_state=parsing_state,
                            primary=primary,
                            entry_data=entry_data,
                            overview=overview,
                            platform_counts=platform_counts,
                            platform_ports=platform_ports,
                            port_lines=port_lines,
                            systems_with_ports=systems_with_ports,
                            port_overview_count=port_overview_count,
                            total_port_lines_all=total_port_lines_all,
                        )

                gh_systems[primary] = entry_data

                # free memory for this <entry>
                elem.clear()

    except ET.ParseError as e:
        log.error(f"XML parse error in {file_path.name}: {e}")
        return False

    log.info(f"Parsed {total_entries} <entry> elements from history.xml")
    log.info(f"  - {systems_count} entries had <systems> (arcade-relevant)")
    log.info(f"  - {software_count} entries had <software> (non-arcade)")
    log.info(f"  - {port_overview_count} entries contained a port overview")

    # Write parsed per-system output (sorted)
    systems_sorted = build_history_systems_sorted(gh_systems)
    
    if not write_json(GH_SYSTEM_PORTS_PATH, systems_sorted, sort_keys=False):  # preserve your explicit order
        return False
    log.info(f"Wrote {GH_SYSTEM_PORTS_PATH} ({len(systems_sorted)} systems)")        

    summary = build_history_summary(
        history_version=history_version,
        history_date=history_date,
        parsing_state=parsing_state,
        systems_count=systems_count,
        software_count=software_count,
        systems_with_ports=systems_with_ports,
        systems_with_aliases=systems_with_aliases,
        total_port_lines_all=total_port_lines_all,
    )

    if not write_json(HISTORY_SUMMARY, summary):  # default sort_keys=True is fine for summaries
        return False
    debug_log(f"Wrote parsing summary to {HISTORY_SUMMARY}")
    
    log.info(f"History parsing completed in {time.perf_counter() - start:.2f} seconds")

    # Cache some tallies for the checker (read-only convenience)
    parsing_state["total_port_lines_all"] = total_port_lines_all
    parsing_state["systems_with_ports_count"] = systems_with_ports
    parsing_state["port_overview_count"] = port_overview_count

    check_history_parse_invariants(
        log=log,
        systems_count=systems_count,
        software_count=software_count,
        total_entries=total_entries,
        gh_systems=gh_systems,
        parsing_state=parsing_state,
        KNOWN_PLATFORMS=KNOWN_PLATFORMS,
    )

    # Success: write the stamp now both outputs are good
    save_stamp(stamp_path, current_stamp)
    return True
