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
from mht.utils.io import write_json


__all__ = [
    "HISTORY_PARSER_SCHEMA",
    "KNOWN_PLATFORMS",
    "segment_text_sections",
    "extract_ports_section",
    "parse_port_entry",
    "parse_history_entries",
]

log = setup_logger(log_level=LOG_LEVEL)
# HISTORY_PARSER_SCHEMA = "1.0"

# Headings like '----- PORTS -----' (case-insensitive).
SECTION_PATTERN = re.compile(r"^-+\s+([A-Z0-9 &]+)\s+-+$", re.IGNORECASE)

# Category headings inside PORTS, e.g. '* CONSOLES:'
CATEGORY_HEADING_PATTERN = re.compile(r"^\*\s*([A-Z0-9 &]+)\s*:\s*$", re.IGNORECASE)

# Expected top-level PORTS categories
KNOWN_PLATFORMS = {"CONSOLES", "COMPUTERS", "HANDHELDS", "OTHERS"}


def segment_text_sections(text: str, parsing_state: dict) -> dict:
    """Split a GH <text> block into named sections; preserve blank lines only in PORTS."""
    sections = defaultdict(list)
    current_section = "OVERVIEW"

    for raw in text.splitlines():
        norm = re.sub(r"\u00A0", " ", raw or "")
        line = norm.strip()

        # dashed section heading
        m = SECTION_PATTERN.match(line)
        if m:
            name = m.group(1).strip().upper()
            current_section = name
            parsing_state.setdefault("section_headings_found", Counter())[name] += 1
            continue

        if line == "":
            if current_section == "PORTS":
                sections[current_section].append("")  # separator marker
            continue

        sections[current_section].append(line)

    return sections


def extract_ports_section(lines: list[str], system_name: str, parsing_state: dict
                          ) -> tuple[str, Counter, dict, int]:
    """
    Parse a PORTS section into overview, category counts, per-category entries, and totals.
    Handles banner inheritance at the start of blocks.
    """
    if "platform_banner_total" not in parsing_state:
        parsing_state["platform_banner_total"] = 0
    if "platform_banners_by_system" not in parsing_state:
        parsing_state["platform_banners_by_system"] = defaultdict(Counter)

    parsing_state.setdefault("null_platform_ports_total", 0)
    parsing_state.setdefault("null_platform_ports_by_system", Counter())
    parsing_state.setdefault("null_platform_examples", defaultdict(list))

    def _norm(s: str) -> str:
        if s is None:
            return ""
        return s.replace("\u00A0", " ").strip()

    def _is_portish(s: str) -> bool:
        t = _norm(s)
        if not t:
            return False
        return ('"' in t) or ('[' in t) or (']' in t) or ('(' in t) or (')' in t) or (':' in t)

    def _looks_like_banner_text(s: str) -> bool:
        t = _norm(s)
        if not t:
            return False
        if t.lstrip().startswith('['):
            return False
        if any(ch in t for ch in ('"', '“', '”', '(', ')', ':')):
            return False
        t_nobr = re.sub(r"\[[^\]]+\]", "", t).strip()
        return bool(re.search(r'[A-Za-z]', t_nobr))

    overview_lines: list[str] = []
    platform_counter: Counter = Counter()
    platform_entries: dict[str, list[dict]] = {}
    current_category: str | None = None
    found_first_category = False
    total_port_lines = 0

    at_block_start: bool = False
    platform_ctx: str | None = None

    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        line = _norm(raw)

        # Category heading
        m = CATEGORY_HEADING_PATTERN.match(line)
        if m:
            cat_name = m.group(1).strip()
            parsing_state.setdefault("platform_categories_found", Counter())[cat_name] += 1

            cat_upper = cat_name.upper()
            if cat_upper in KNOWN_PLATFORMS:
                platform_counter[cat_upper] += 1
                platform_entries.setdefault(cat_upper, [])
                current_category = cat_upper
                found_first_category = True
                at_block_start = True
                platform_ctx = None
            else:
                parsing_state.setdefault("unexpected_platform_categories", defaultdict(list))[cat_name].append(system_name)
                current_category = None
                at_block_start = False
                platform_ctx = None
            i += 1
            continue

        if not found_first_category:
            if line:
                overview_lines.append(line)
            i += 1
            continue

        if not line:
            at_block_start = True
            platform_ctx = None
            i += 1
            continue

        if at_block_start and _looks_like_banner_text(line):
            # lookahead within block
            j = i + 1
            next_nonempty = None
            while j < n:
                nxt = _norm(lines[j])
                if not nxt:
                    break
                if CATEGORY_HEADING_PATTERN.match(nxt):
                    break
                next_nonempty = nxt
                break
            if next_nonempty and _is_portish(next_nonempty):
                parsing_state["platform_banner_total"] += 1
                parsing_state["platform_banners_by_system"][system_name][line] += 1
                platform_ctx = line
                at_block_start = False
                i += 1
                continue

        if current_category:
            parsed = parse_port_entry(line, system_name=system_name, parsing_state=parsing_state)

            if not parsed.get("platform") and platform_ctx:
                parsed["platform"] = platform_ctx
                platforms = parsing_state.setdefault(
                    "platforms_found", defaultdict(lambda: {"count": 0, "systems": []})
                )
                platforms[platform_ctx]["count"] += 1
                platforms[platform_ctx]["systems"].append(system_name)

            if not parsed.get("platform"):
                parsing_state["null_platform_ports_total"] += 1
                parsing_state["null_platform_ports_by_system"][system_name] += 1
                ex = parsing_state["null_platform_examples"][system_name]
                if len(ex) < 3:
                    ex.append(line[:200])

            platform_entries[current_category].append(parsed)
            total_port_lines += 1

        at_block_start = False
        i += 1

    overview = " ".join(overview_lines).strip() if overview_lines else ""
    if not found_first_category:
        text = " ".join(overview_lines).strip()
        excerpt = text[:140]
        (parsing_state
         .setdefault("anomalies", {})
         .setdefault("ports_missing_subheadings", [])
         .append({"system": system_name, "excerpt": excerpt}))
    return overview, platform_counter, platform_entries, total_port_lines


def parse_port_entry(line: str, system_name: str = "", parsing_state: dict = None) -> dict:
    """Parse a single PORTS line into structured fields."""
    port = {
        "regions": [],
        "platform": None,
        "model": [],
        "title": None,
        "date": None,
        "publisher": None,
        "comment": None,
        "additional_tags": [],
        "residue": []
    }

    original_line = (line or "").strip()
    working_line = original_line

    def _mark_residue():
        parsing_state.setdefault("systems_with_residue", set()).add(system_name)

    def _split_comment_outside_quotes(s: str) -> tuple[str, str | None]:
        """Split on first ':' outside quotes; ignore floppy-inch marks (3.5", 5.25")."""
        idx = -1
        in_quotes = False
        for i, ch in enumerate(s):
            if ch == '"':
                window = s[max(0, i-4):i+1]
                m = re.search(r'(3\.5|5\.25)"$', window)
                if m:
                    if parsing_state is not None and system_name:
                        size = m.group(1)
                        parsing_state.setdefault("disk_size_quotes", defaultdict(list))
                        parsing_state["disk_size_quotes"][size].append(system_name)
                    continue
                in_quotes = not in_quotes
            elif ch == ':' and not in_quotes:
                idx = i
                break
        if idx != -1:
            return s[:idx].rstrip(), s[idx + 1:].strip()
        return s, None

    def _strip_square_brackets_exact_once(s: str, payloads: list[str]) -> str:
        out = s
        for payload in payloads:
            out = out.replace(f"[{payload}]", "")
        return out

    def _strip_all_square_brackets(s: str) -> str:
        return re.sub(r"\[[^\]]*\]", "", s)

    def _strip_first_quoted_title(s: str) -> tuple[str, str | None]:
        m = re.search(r'"(.*?)"', s)
        if not m:
            return s, None
        return s.replace(m.group(0), ""), (m.group(1).strip() if m.group(1) else "")

    def _strip_first_parentheses_and_after(s: str) -> tuple[str, str | None, str]:
        m = re.search(r"\((.*?)\)", s)
        if not m:
            return s, None, ""
        pre = s[: m.start()].strip()
        date_raw = m.group(1).strip()
        post = s[m.end():].strip()
        return pre, date_raw, post

    def _fallback_platform_from_original(src: str) -> str | None:
        base, _comment = _split_comment_outside_quotes(src)
        base = _strip_all_square_brackets(base)
        base = re.sub(r'"[^"]*"', "", base)
        base = re.sub(r"\([^)]*\)", "", base)
        cand = base.strip()
        return cand or None

    # anomalies (odd quotes/brackets), ignoring inch marks
    disk_quote_matches = re.findall(r'\b(?:3\.5|5\.25)"(?!\w)', working_line)
    quote_count = working_line.count('"') - len(disk_quote_matches)
    bracket_count = (working_line.count('(') + working_line.count(')') +
                     working_line.count('[') + working_line.count(']') +
                     working_line.count('{') + working_line.count('}'))
    if quote_count % 2 == 1:
        parsing_state.setdefault("odd_quotes", defaultdict(list))[system_name].append(working_line)
    if bracket_count % 2 == 1:
        parsing_state.setdefault("odd_brackets", defaultdict(list))[system_name].append(working_line)

    # 1) comment
    working_line, comment = _split_comment_outside_quotes(working_line)
    if comment:
        port["comment"] = comment
        parsing_state["ports_with_comments"] += 1

    # 2) [ ... ] tags (regions/models/additional)
    square_brackets = re.findall(r"\[(.*?)\]", working_line)
    for tag in square_brackets:
        tag_clean = tag.strip()
        if tag_clean.startswith("Model"):
            model_raw = tag_clean.replace("Model", "").strip()
            models: list[str] = []
            if "/" in model_raw:
                models = [m.strip() for m in model_raw.split("/")]
            elif "(" in model_raw and ")" in model_raw:
                match = re.match(r"^(.*?)\s*\((.*?)\)", model_raw)
                if match:
                    model_main = match.group(1).strip()
                    model_alt = match.group(2).strip()
                    if model_main[:4] == model_alt[:4]:
                        models = [model_main, model_alt]
                    else:
                        models = [model_raw]
                else:
                    models = [model_raw]
            else:
                models = [model_raw]
            port["model"] = models
            for model in models:
                parsing_state["models_found"][model].append(system_name)
        elif len(tag_clean) == 2:
            port["regions"].append(tag_clean)
        else:
            port["additional_tags"].append(tag_clean)

    working_line = _strip_square_brackets_exact_once(working_line, square_brackets)

    # 3) title
    working_line, title = _strip_first_quoted_title(working_line)
    if title:
        port["title"] = title

    # 4) date (+publisher tail)
    working_line, date_raw, post_date_text = _strip_first_parentheses_and_after(working_line)
    if date_raw:
        normalised = parse_date_string(date_raw, context=system_name)
        if normalised:
            port["date"] = normalised
        else:
            port["residue"].append(date_raw)
            parsing_state.setdefault("unparsable_dates", defaultdict(list))[system_name].append(date_raw)
            _mark_residue()

        zone = (post_date_text or "").strip()
        if zone:
            m = re.match(r'^(released\s+by|by)\b', zone, flags=re.IGNORECASE)
            if m:
                if m.group(1).lower().startswith("released"):
                    parsing_state["publisher_indicators_found"]["released_by"] += 1
                else:
                    parsing_state["publisher_indicators_found"]["by"] += 1
            else:
                parsing_state["publisher_indicators_found"]["other_after_date"] += 1
        else:
            parsing_state["publisher_indicators_found"]["none"] += 1

        if post_date_text:
            cleaned = re.sub(r"^\s*by\s+", "", post_date_text, flags=re.IGNORECASE).strip()
            cleaned = re.sub(r"^\s*-\s*", "", cleaned).rstrip(".:; ")
            port["publisher"] = cleaned
            pub = parsing_state["publishers_found"][cleaned]
            pub["count"] += 1
            pub["systems"].append(system_name)
    else:
        if re.search(r"\breleased\s+by\b", working_line, flags=re.IGNORECASE):
            parsing_state["publisher_indicators_found"]["released_by"] += 1
        elif re.search(r"\bby\b", working_line, flags=re.IGNORECASE):
            parsing_state["publisher_indicators_found"]["by"] += 1
        else:
            parsing_state["publisher_indicators_found"]["none"] += 1

        match_pub = re.search(r"\bby\s+(.+)", working_line, flags=re.IGNORECASE)
        if match_pub:
            cleaned = match_pub.group(1).strip()
            cleaned = re.sub(r"^\s*-\s*", "", cleaned).rstrip(".:; ")
            port["publisher"] = cleaned
            pub = parsing_state["publishers_found"][cleaned]
            pub["count"] += 1
            pub["systems"].append(system_name)
            working_line = working_line[:match_pub.start()].strip()

    # 5) platform candidate
    platform_candidate = working_line.strip()
    if not platform_candidate:
        platform_candidate = _fallback_platform_from_original(original_line)

    if platform_candidate:
        port["platform"] = platform_candidate
        platforms = parsing_state.setdefault("platforms_found", defaultdict(lambda: {"count": 0, "systems": []}))
        platforms[platform_candidate]["count"] += 1
        platforms[platform_candidate]["systems"].append(system_name)

    if port["title"]:
        parsing_state["titles_found"].add(port["title"])
    for region in port["regions"]:
        parsing_state["region_codes"][region] += 1
    if port["model"]:
        for model in port["model"]:
            parsing_state["models_found"][model].append(system_name)
    if port["comment"]:
        parsing_state.setdefault("comments_found", defaultdict(list))[port["comment"]].append(system_name)
    for tag in port["additional_tags"]:
        parsing_state["additional_tags_found"][tag].append(system_name)

    return port


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
    try:
        write_json(GH_SYSTEM_PORTS_PATH, systems_sorted, sort_keys=False)  # keep your case-insensitive order                     
        log.info(f"Wrote {GH_SYSTEM_PORTS_PATH} ({len(systems_sorted)} systems)")
    except Exception as e:
        log.error(f"Failed to write GH systems JSON: {e}")
        return False

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

    try:
        write_json(HISTORY_SUMMARY, summary)  # sorted keys are fine for summaries
        debug_log(f"Wrote parsing summary to {HISTORY_SUMMARY}")
    except Exception as e:
        log.warning(f"Could not write parsing summary: {e}")
        return False

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
