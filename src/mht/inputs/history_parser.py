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
Schema: HISTORY_PARSER_SCHEMA = "1.0"
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
from mht.utils.logger import setup_logger, debug_log
from mht.utils.date_utils import parse_date_string
from mht.utils.versions import SCHEMA_IDS, schema_version, tool_version
from mht.utils.stamps import make_stamp, load_stamp, save_stamp, is_fresh
from mht.utils.paths import (
    STAMPS_DIR,
    GH_SYSTEM_PORTS_PATH,
    HISTORY_SUMMARY,
)
from mht.utils.headers import build_summary_header
from mht.utils.io import write_json, read_json
from mht.utils.ports import (
    is_valid_port_row as _is_valid_port_row,
    norm_regions      as _norm_regions,
    norm_tags         as _norm_tags,
)
from mht.inputs.history_constants import (
    SECTION_PATTERN,
    CATEGORY_HEADING_PATTERN,
    KNOWN_PLATFORMS,
)
from mht.inputs.history_ports import (
    segment_text_sections,
    extract_ports_section,
    parse_port_entry,
)


__all__ = [
    "HISTORY_PARSER_SCHEMA",
    "parse_port_entry",
    "parse_history_entries",
]

log = setup_logger(log_level=LOG_LEVEL)
# HISTORY_PARSER_SCHEMA = "1.0"


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
        inputs=[file_path],
    )
    prev = load_stamp(stamp_path)
    if is_fresh(current_stamp, prev):
        log.info("History stage up-to-date (stamp matched) — skipping parse")
        return True

    try:
        for event, elem in ET.iterparse(file_path, events=("start",)):
            if elem.tag.lower() == "history":
                history_version = elem.attrib.get("version")
                history_date = elem.attrib.get("date")
                break
    except ET.ParseError:
        log.warning("Could not read history root attributes for summary header")

    # ----------------------------
    # Parsing state
    # ----------------------------
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
        with open(file_path, encoding=encoding) as f:
            for event, elem in ET.iterparse(f, events=("end",)):
                if elem.tag != "entry":
                    continue

                total_entries += 1
                if (total_entries % 10000) == 0:
                    log.info(f"[history_parser::parse_history_entries] Parsed {total_entries:,} entries so far...")

                entry_data = {"gh_id": None, "aliases": [], "port_overview": "", "ports": {}}

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

                    if "CONTRIBUTE" in sectioned:
                        for line in sectioned["CONTRIBUTE"]:
                            m = re.search(r"id=(\d+)", line)
                            if m:
                                entry_data["gh_id"] = int(m.group(1))
                                break

                    if "PORTS" in sectioned:
                        systems_with_ports += 1
                        overview, platform_counts, platform_ports, port_lines = extract_ports_section(
                            sectioned["PORTS"], primary, parsing_state
                        )
                        total_port_lines_all += port_lines

                        if overview:
                            entry_data["port_overview"] = overview
                            parsing_state["systems_with_port_overview"][primary] = overview
                            port_overview_count += 1

                        if platform_ports:
                            entry_data["ports"] = platform_ports

                        if platform_counts:
                            for cat, c in platform_counts.items():
                                parsing_state["platform_categories_found"][cat] += c

                gh_systems[primary] = entry_data
                elem.clear()

    except ET.ParseError as e:
        log.error(f"XML parse error in {file_path.name}: {e}")
        return False

    log.info(f"Parsed {total_entries} <entry> elements from history.xml")
    log.info(f"  - {systems_count} entries had <systems> (arcade-relevant)")
    log.info(f"  - {software_count} entries had <software> (non-arcade)")
    log.info(f"  - {port_overview_count} entries contained a port overview")

    # ----------------------------
    # Write parsed per-system output (sorted)
    # ----------------------------
    systems_sorted = {k: gh_systems[k] for k in sorted(gh_systems.keys(), key=str.lower)}
    
    if not write_json(GH_SYSTEM_PORTS_PATH, systems_sorted, sort_keys=False):  # preserve your explicit order
        return False
    log.info(f"Wrote {GH_SYSTEM_PORTS_PATH} ({len(systems_sorted)} systems)")        
    
    #try:
    #    write_json(GH_SYSTEM_PORTS_PATH, systems_sorted, sort_keys=False)  # keep your case-insensitive order                     
    #    log.info(f"Wrote {GH_SYSTEM_PORTS_PATH} ({len(systems_sorted)} systems)")
    #except Exception as e:
    #    log.error(f"Failed to write GH systems JSON: {e}")
    #    return False

    # ----------------------------
    # Build summary JSON
    # ----------------------------
    platforms_found_summary = {}
    for platform, data in parsing_state["platforms_found"].items():
        systems_unique = sorted(set(data["systems"]))
        platforms_found_summary[platform] = {"systems_count": len(systems_unique), "systems": systems_unique}

    _section_heads = dict(parsing_state["section_headings_found"])
    section_headings_block = {
        "unique": len(_section_heads),
        "distribution": dict(sorted(_section_heads.items(), key=lambda kv: kv[0].upper())),
    }

    _cats = dict(parsing_state["platform_categories_found"])
    platform_categories_block = {
        "unique": len(_cats),
        "distribution": dict(sorted(_cats.items(), key=lambda kv: kv[0].upper())),
    }

    summary_platforms_block = {
        "unique": len(platforms_found_summary),
        "by_platform": dict(sorted(platforms_found_summary.items(), key=lambda kv: kv[0].lower())),
    }

    _publishers_map = parsing_state["publishers_found"]
    _by_publisher = {}
    for name, data in _publishers_map.items():
        systems_unique = sorted(set(data["systems"]))
        _by_publisher[name] = {"systems_count": len(systems_unique), "systems": systems_unique}

    publishers_block = {
        "unique": len(_by_publisher),
        "indicators_found": {
            k: parsing_state["publisher_indicators_found"].get(k, 0)
            for k in ("by", "released_by", "other_after_date", "none")
        },
        "by_publisher": dict(sorted(_by_publisher.items(), key=lambda kv: kv[0].lower())),
    }

    titles_items = sorted(parsing_state["titles_found"])
    titles_block = {"unique": len(titles_items), "items": titles_items}

    _region = parsing_state["region_codes"]
    region_codes_block = {"unique": len(_region), "distribution": dict(sorted(_region.items(), key=lambda kv: (-kv[1], kv[0])))}  # fmt: skip

    models_items = sorted(parsing_state["models_found"].keys())
    models_block = {"unique": len(models_items), "items": models_items}

    _comments_map = parsing_state["comments_found"]
    comments_block = {
        "unique": len(_comments_map),
        "by_comment": {c: sorted(set(sys)) for c, sys in sorted(_comments_map.items(), key=lambda kv: kv[0].lower())},
    }

    _tags_map = parsing_state["additional_tags_found"]
    additional_tags_block = {
        "unique": len(_tags_map),
        "by_tag": {
            tag: {"systems_count": len(set(s)), "systems": sorted(set(s))}
            for tag, s in sorted(_tags_map.items(), key=lambda kv: kv[0].lower())
        },
    }

    overviews_map = parsing_state["systems_with_port_overview"]
    port_overview_block = {"count": len(overviews_map), "by_system": dict(sorted(overviews_map.items(), key=lambda kv: kv[0].lower()))}

    _upc_map = parsing_state["unexpected_platform_categories"]
    _by_category = {}
    systems_affected_set = set()
    for cat, systems in _upc_map.items():
        uniq = sorted(set(systems))
        systems_affected_set.update(uniq)
        _by_category[cat] = {"systems_count": len(uniq), "systems": uniq}
    unexpected_platform_categories_block = {
        "unique": len(_by_category),
        "systems_affected": len(systems_affected_set),
        "by_category": dict(sorted(_by_category.items(), key=lambda kv: kv[0].lower())),
    }

    _oddq_map = parsing_state["odd_quotes"]
    odd_number_of_quotes_block = {
        "count": sum(len(v) for v in _oddq_map.values()),
        "systems_affected": len(_oddq_map),
        "by_system": {sys: lines for sys, lines in sorted(_oddq_map.items(), key=lambda kv: kv[0].lower())},
    }

    _oddb_map = parsing_state["odd_brackets"]
    odd_number_of_brackets_block = {
        "count": sum(len(v) for v in _oddb_map.values()),
        "systems_affected": len(_oddb_map),
        "by_system": {sys: lines for sys, lines in sorted(_oddb_map.items(), key=lambda kv: kv[0].lower())},
    }

    _pms_list = parsing_state.get("anomalies", {}).get("ports_missing_subheadings", [])
    _pms_map = {}
    for rec in _pms_list:
        sys = rec.get("system")
        exc = rec.get("excerpt", "")
        if sys:
            _pms_map[sys] = exc
    ports_missing_subheadings_block = {"count": len(_pms_map), "by_system": dict(sorted(_pms_map.items(), key=lambda kv: kv[0].lower()))}

    _ud_map = parsing_state["unparsable_dates"]
    unparsable_dates_block = {
        "count": sum(len(v) for v in _ud_map.values()),
        "systems_affected": len(_ud_map),
        "by_system": {sys: dates for sys, dates in sorted(_ud_map.items(), key=lambda kv: kv[0].lower())},
    }

    _swr_items = sorted(parsing_state["systems_with_residue"])
    systems_with_residue_block = {"count": len(_swr_items), "items": _swr_items}

    _dsq = parsing_state["disk_size_quotes"]
    disk_size_quotes_block = {
        "unique": len(_dsq),
        "distribution": {
            size: {"count": len(set(systems)), "systems": sorted(set(systems))}
            for size, systems in sorted(_dsq.items(), key=lambda kv: kv[0])
        },
    }

    #generated_at_utc = datetime.datetime.utcnow().isoformat() + "Z"

    header = build_summary_header(
        schema_id=SCHEMA_IDS["history"],
        schema_version=schema_version(SCHEMA_IDS["history"]),
        versions={
            "gh_version": history_version,
            "gh_date": history_date,
            "history_parser_version": tool_version("history_parser"),
        },
    )

    summary = {
        "header": header,
        "totals": {
            "systems_total": systems_count,
            "software_total": software_count,
            "entries_total": systems_count + software_count,
            "total_systems": systems_count,
            "total_software": software_count,
            "total_entries": systems_count + software_count,
            "systems_with_ports": systems_with_ports,
            "systems_with_aliases": systems_with_aliases,
            "port_lines_parsed": total_port_lines_all,
            "publisher_count_unique": len(parsing_state["publishers_found"]),
            "platform_count_unique": len(platforms_found_summary),
            "model_count_unique": len(models_items := models_items if 'models_items' in locals() else sorted(parsing_state["models_found"].keys())),
            "additional_tag_count_unique": len(_tags_map),
            "ports_with_comments": parsing_state["ports_with_comments"],
            "systems_with_port_overview": port_overview_block["count"],
        },
        "found": {
            "section_headings_found": section_headings_block,
            "platform_categories_found": platform_categories_block,
            "platforms_found": summary_platforms_block,
            "publishers_found": publishers_block,
            "titles_found": titles_block,
            "region_codes": region_codes_block,
            "models_found": {"unique": len(models_items), "items": models_items},
            "comments_found": comments_block,
            "additional_tags_found": additional_tags_block,
            "disk_size_quotes": disk_size_quotes_block,
            "port_overview_texts": port_overview_block,
        },
        "anomalies": {
            "unexpected_platform_categories": unexpected_platform_categories_block,
            "odd_number_of_quotes": odd_number_of_quotes_block,
            "odd_number_of_brackets": odd_number_of_brackets_block,
            "ports_missing_subheadings": ports_missing_subheadings_block,
            "platform_banners": {
                "count": parsing_state["platform_banner_total"],
                "systems_affected": len(parsing_state["platform_banners_by_system"]),
                "by_system": {
                    sys: {"count": sum(counter.values()), "banners": dict(counter)}
                    for sys, counter in sorted(parsing_state["platform_banners_by_system"].items())
                },
            },
            "null_platform_ports": {
                "count": parsing_state["null_platform_ports_total"],
                "systems_affected": len(parsing_state["null_platform_ports_by_system"]),
                "by_system": dict(sorted(parsing_state["null_platform_ports_by_system"].items(), key=lambda kv: (-kv[1], kv[0]))),
                "by_system_lines": {k: v for k, v in parsing_state["null_platform_examples"].items()},
            },
        },
        "residue_flags": {
            "unparsable_dates": unparsable_dates_block,
            "systems_with_residue": systems_with_residue_block,
        },
    }

    if not write_json(HISTORY_SUMMARY, summary):  # sorted keys are fine for summaries (default True)
        return False
    debug_log(f"Wrote parsing summary to {HISTORY_SUMMARY}")

    #try:
    #    write_json(HISTORY_SUMMARY, summary)  # sorted keys are fine for summaries
    #    debug_log(f"Wrote parsing summary to {HISTORY_SUMMARY}")
    #except Exception as e:
    #    log.warning(f"Could not write parsing summary: {e}")
    #    return False

    log.info(f"History parsing completed in {time.perf_counter() - start:.2f} seconds")

    # Invariants (warnings only)
    issues = 0

    def _warn_ok(cond: bool, msg: str):
        nonlocal issues
        if not cond:
            issues += 1
            log.warning(msg)

    _warn_ok(
        systems_count + software_count == total_entries,
        f"[history_parser] systems+software != total_entries ({systems_count}+{software_count}!={total_entries})",
    )
    _warn_ok(len(gh_systems) == systems_count, f"[history_parser] gh_systems count {len(gh_systems)} != systems_count {systems_count}")
    platform_hits = sum(d["count"] for d in parsing_state["platforms_found"].values())
    null_pl = parsing_state["null_platform_ports_total"]
    _warn_ok(
        platform_hits + null_pl == total_port_lines_all,
        "[history_parser] platforms_found + null_platforms != port_lines_parsed",
    )
    _warn_ok(sum(parsing_state["null_platform_ports_by_system"].values()) == null_pl,
             "[history_parser] per-system null platform sum mismatch")
    banner_total_calc = sum(sum(c.values()) for c in parsing_state["platform_banners_by_system"].values())
    _warn_ok(banner_total_calc == parsing_state["platform_banner_total"],
             "[history_parser] platform_banner_total mismatch")
    _warn_ok(systems_with_ports <= systems_count,
             f"[history_parser] systems_with_ports {systems_with_ports} > systems_count {systems_count}")
    _warn_ok(port_overview_count <= systems_with_ports,
             f"[history_parser] port_overview_count {port_overview_count} > systems_with_ports {systems_with_ports}")
    unknown_cats = [k for k in parsing_state["platform_categories_found"].keys() if k.upper() not in KNOWN_PLATFORMS]
    if unknown_cats:
        log.info("[history_parser] unexpected PORTS categories: %s", ", ".join(sorted(set(unknown_cats))))
    _warn_ok(
        len(parsing_state.get("systems_with_residue", set())) >= len(parsing_state.get("unparsable_dates", {})),
        "[history_parser] systems_with_residue fewer than unparsable_dates keys",
    )
    if issues == 0:
        log.info("[history_parser] invariants passed")

    # Success: write the stamp now both outputs are good
    save_stamp(stamp_path, current_stamp)
    return True
