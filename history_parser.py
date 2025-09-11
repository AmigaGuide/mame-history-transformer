"""
Filename: history_parser.py
Version: 1.0.0
Last modified: 2025-09-10
Author: Jason (XtC) Skelly (Open University TM470, 2025)

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

Key behaviours:
- Uses ElementTree.iterparse() to stream and bound memory.
- Preserves raw text (no editorial changes); normalises NBSP only for separator logic.
- Detects and audits platform banners; inherits banner platform when rows omit it.
- Treats floppy disk inch marks (e.g. 3.5", 5.25", 3.25", 8") as literals, not quotes.
- Auditing: Includes platform banners and inheritance, disk-size quote handling,
  null-platform rows, odd quotes/brackets, missing PORTS subheadings, publisher
  indicators, and distribution counts (platforms, models, regions, tags).
  See data/history_parsing_summary.json for full details.

Logging:
- Configured via config.LOG_LEVEL and logger.setup_logger; writes informative and
  warning diagnostics, plus end-of-run invariants to validate counts.

Runtime:
- Python 3.10+ recommended.
- Standard library only (xml.etree.ElementTree, re, json, html, collections, etc.).

Licence:
This file forms part of a student project and is not intended for commercial use.
See repository LICENCE for details.
"""

from pathlib import Path
import xml.etree.ElementTree as ET
import time
import re
import json
import html
from collections import Counter, defaultdict
import datetime

from config import LOG_LEVEL
from logger import setup_logger, debug_log
from date_utils import parse_date_string

__all__ = [
    "HISTORY_PARSER_SCHEMA",
    "KNOWN_PLATFORMS",
    "segment_text_sections",
    "extract_ports_section",
    "parse_port_entry",
    "parse_history_entries",
]

log = setup_logger(log_level=LOG_LEVEL)

HISTORY_PARSER_SCHEMA = "1.0"

# Headings like '----- PORTS -----' (case-insensitive). Captures the name between dashes.
# Note: GH content sometimes uses mixed case, hence re.IGNORECASE.
SECTION_PATTERN = re.compile(r"^-+\s+([A-Z0-9 &]+)\s+-+$", re.IGNORECASE)

# Category headings inside PORTS, e.g. '* CONSOLES:' (bullet optional spacing).
CATEGORY_HEADING_PATTERN = re.compile(r"^\*\s*([A-Z0-9 &]+)\s*:\s*$", re.IGNORECASE)

# Expected top-level PORTS categories; anything else is reported under anomalies.
KNOWN_PLATFORMS = {"CONSOLES", "COMPUTERS", "HANDHELDS", "OTHERS"}

def segment_text_sections(text: str, parsing_state: dict) -> dict:
    """
    Split a Gaming-History <text> block into named sections.

    Parses dashed headings such as '----- PORTS -----', preserves true blank lines
    only within the PORTS section (to support platform-banner detection), and
    increments the section heading counters in `parsing_state`.

    Args:
      text: Raw, HTML-unescaped text content from a single <entry>/<text>.
      parsing_state: Mutable state dictionary used to collect parsing counters.

    Returns:
      A mapping of section name to list of normalised lines. The "OVERVIEW" key is
      used for content prior to the first recognised section heading.

    Notes:
      Non-breaking spaces are normalised to regular spaces so that visually blank
      lines become truly blank and act as separators in PORTS.
    """
    sections = defaultdict(list)
    current_section = "OVERVIEW"

    for raw in text.splitlines():
        # NBSP → space so visually blank lines become true separators in PORTS.
        norm = re.sub(r"\u00A0", " ", raw or "")
        line = norm.strip()

        # Section heading like '----- PORTS -----'
        match = SECTION_PATTERN.match(line)
        # Count every section heading encountered (used for a site-wide distribution).
        if match:
            section_name = match.group(1).strip().upper()
            current_section = section_name
            parsing_state.setdefault("section_headings_found", Counter())[section_name] += 1
            continue

        # Preserve true blank lines *only* within PORTS to act as separators
        if line == "":
            if current_section == "PORTS":
                sections[current_section].append("")  # separator marker
            # for other sections, ignore blanks as before
            continue

        # Regular content line
        sections[current_section].append(line)

    return sections

def extract_ports_section(lines: list[str], system_name: str, parsing_state: dict
                          ) -> tuple[str, Counter, dict, int]:
    """
    Parse a PORTS section into overview, category counts, per-category entries, and totals.

    Implements platform-banner detection at the start of category blocks (CONSOLES,
    COMPUTERS, HANDHELDS, OTHERS). When a banner is found, it is recorded for audit
    and inherited as the platform by subsequent port rows that do not specify one.

    Args:
      lines: The PORTS section lines including blank separators.
      system_name: The primary Gaming-History system name for this entry.
      parsing_state: Mutable state dictionary for counters, audits, and anomalies.

    Returns:
      A 4-tuple:
        - overview (str): Concatenated overview text prior to the first category.
        - platform_counter (Counter): Counts of category headings encountered.
        - platform_entries (dict): Mapping category -> list of parsed port dicts.
        - total_port_lines (int): Total number of concrete port rows parsed.

    Notes:
      - Banner logic only triggers at block start (immediately after a heading or
        a truly blank line) and only if the next non-empty line is plausibly port
        shaped (quotes, brackets, parentheses, or a colon).
      - Null-platform rows (even after inheritance) are tracked under anomalies.
    """
    if "platform_banner_total" not in parsing_state:
        parsing_state["platform_banner_total"] = 0
    if "platform_banners_by_system" not in parsing_state:
        parsing_state["platform_banners_by_system"] = defaultdict(Counter)

    parsing_state.setdefault("null_platform_ports_total", 0)
    parsing_state.setdefault("null_platform_ports_by_system", Counter())
    parsing_state.setdefault("null_platform_examples", defaultdict(list))

    def _norm(s: str) -> str:
        """Normalise a line: convert NBSP to space, strip edges only, preserve internal spacing; None → ''. """
        if s is None:
            return ""
        return s.replace("\u00A0", " ").strip()
       
    def _is_portish(s: str) -> bool:
        """Return True if the line looks like a port row (quotes/brackets/parens/colon)."""
        t = _norm(s)
        if not t:
            return False
        return ('"' in t) or ('[' in t) or (']' in t) or ('(' in t) or (')' in t) or (':' in t)

    def _looks_like_banner_text(s: str) -> bool:
        """Return True if the line is a platform banner – not starting with '[', no quotes/parens/colon; 
        bracket qualifiers allowed only if not leading and there is at least one letter."""
        t = _norm(s)
        if not t:
            return False
        if t.lstrip().startswith('['):
            return False
        if any(ch in t for ch in ('"', '“', '”', '(', ')', ':')):
            return False
        t_nobrackets = re.sub(r"\[[^\]]+\]", "", t).strip()
        return bool(re.search(r'[A-Za-z]', t_nobrackets))

    # --- state ----------------------------------------------------------------
    overview_lines: list[str] = []
    platform_counter: Counter = Counter()
    platform_entries: dict[str, list[dict]] = {}
    current_category: str | None = None
    found_first_category = False
    total_port_lines = 0

    # Gate: only consider banners right after a heading or a blank line
    at_block_start: bool = False
    # INHERIT: current banner label for subsequent port rows
    platform_ctx: str | None = None

    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        line = _norm(raw)
        
        # Only treat a line as a banner at block start *and* if the next non-empty line looks port-like.
        # Category heading like "* CONSOLES:"
        m = CATEGORY_HEADING_PATTERN.match(line)
        if m:
            category_name = m.group(1).strip()
            parsing_state.setdefault("platform_categories_found", Counter())[category_name] += 1

            category_upper = category_name.upper()
            if category_upper in KNOWN_PLATFORMS:
                platform_counter[category_upper] += 1
                platform_entries.setdefault(category_upper, [])
                current_category = category_upper
                found_first_category = True
                at_block_start = True
                platform_ctx = None
            else:
                parsing_state.setdefault("unexpected_platform_categories", defaultdict(list))[category_name].append(system_name)
                current_category = None
                at_block_start = False
                platform_ctx = None
            i += 1
            continue

        # Before first recognised category: accumulate overview
        if not found_first_category:
            if line:
                overview_lines.append(line)
            i += 1
            continue

        # Truly blank line ends a block; next non-empty can start a new banner block
        if not line:
            at_block_start = True
            platform_ctx = None
            i += 1
            continue

        # Inside a recognised category block
        # Accept banners ONLY at block start, and only if the next non-empty is portish
        if at_block_start and _looks_like_banner_text(line):
            # Look ahead to the next non-empty, non-heading line within the same block
            j = i + 1
            next_nonempty = None
            while j < n:
                nxt = _norm(lines[j])
                if not nxt:
                    break  # blank line ends the block
                if CATEGORY_HEADING_PATTERN.match(nxt):
                    break  # next category starts
                next_nonempty = nxt
                break

            if next_nonempty and _is_portish(next_nonempty):
                # Audit banner, set platform context; not a port row.
                parsing_state["platform_banner_total"] += 1
                parsing_state["platform_banners_by_system"][system_name][line] += 1
                platform_ctx = line
                at_block_start = False
                i += 1
                continue

        # Otherwise, treat as a real port row
        if current_category:
            parsed_entry = parse_port_entry(line, system_name=system_name, parsing_state=parsing_state)

            # No inline platform → inherit current banner.
            if not parsed_entry.get("platform") and platform_ctx:
                parsed_entry["platform"] = platform_ctx
                # reflect in platforms_found (avoid double counting inline platform cases)
                platforms = parsing_state.setdefault(
                    "platforms_found", defaultdict(lambda: {"count": 0, "systems": []})
                )
                platforms[platform_ctx]["count"] += 1
                platforms[platform_ctx]["systems"].append(system_name)

            # Still no platform after inheritance → record anomaly (manual review).
            if not parsed_entry.get("platform"):
                parsing_state["null_platform_ports_total"] += 1
                parsing_state["null_platform_ports_by_system"][system_name] += 1
                ex = parsing_state["null_platform_examples"][system_name]
                if len(ex) < 3:
                    ex.append(line[:200])

            platform_entries[current_category].append(parsed_entry)
            total_port_lines += 1

        # After any non-empty line, we're no longer at block start
        at_block_start = False
        i += 1

    # Overview text + anomaly if no recognised category headings were found
    overview = " ".join(overview_lines).strip() if overview_lines else ""
    if not found_first_category:
        text = " ".join(overview_lines).strip()
        excerpt = text[:140]  # fixed 140 characters
        (parsing_state
            .setdefault("anomalies", {})
            .setdefault("ports_missing_subheadings", [])
            .append({"system": system_name, "excerpt": excerpt}))

    return overview, platform_counter, platform_entries, total_port_lines

def parse_port_entry(line: str, system_name: str = "", parsing_state: dict = None) -> dict:
    """
    Parse a single port line into structured fields.

    Extracts regions, platform, model identifiers, title, date, publisher, comment,
    and additional tags. Handles comments using the first colon outside quotes.
    Disk-size inch marks (for example 3.5", 5.25", 3.25", 8") do not toggle the
    in-quotes state, preventing misclassification of comments and publishers.

    Args:
      line: A single normalised PORTS line.
      system_name: The GH system this line belongs to (for audits).
      parsing_state: Mutable state dictionary for counters, audits, and anomalies.

    Returns:
      A dict with:
        - regions (list[str])
        - platform (str | None)
        - model (list[str])
        - title (str | None)
        - date (str | None)  # ISO-like normalised by parse_date_string
        - publisher (str | None)
        - comment (str | None)
        - additional_tags (list[str])
        - residue (list[str])  # unparsed fragments such as unrecognised dates

    Notes:
      - The colon splitter ignores colons inside real quoted titles but also ignores
        floppy disk inch marks when accounting for quotes.
      - Publisher indicators (“by”, “released by”) are counted for summary metrics.
    """
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
        """
        Flag that this system produced leftover, unparsed fragments.

        Side effects:
            Adds the current system_name (from the closure) to
            parsing_state["systems_with_residue"], which is later summarised
            under residue_flags.systems_with_residue.
        """
        parsing_state.setdefault("systems_with_residue", set()).add(system_name)

    def _split_comment_outside_quotes(s: str) -> tuple[str, str | None]:       
        """Split on first ':' outside quotes; disk-size inch marks (3", 3.25", 3.5", 5.25", 8") do not toggle."""
        idx = -1
        in_quotes = False
        for i, ch in enumerate(s):
            if ch == '"':
                # Look behind a few characters for disk size patterns
                window = s[max(0, i-4):i+1]  # captures '3.5"' or '5.25"'
                m = re.search(r'(3\.5|5\.25)"$', window)
                if m:
                    # record audit trail using variables from the outer scope (closure)
                    if parsing_state is not None and system_name:
                        size = m.group(1)  # '3.5' or '5.25'
                        parsing_state.setdefault("disk_size_quotes", defaultdict(list))
                        parsing_state["disk_size_quotes"][size].append(system_name)
                    continue  # do not toggle in_quotes for disk-size markers

                # normal quote toggling
                in_quotes = not in_quotes

            elif ch == ':' and not in_quotes:
                idx = i
                break

        if idx != -1:
            return s[:idx].rstrip(), s[idx + 1:].strip()
        return s, None

    def _strip_square_brackets_exact_once(s: str, bracket_payloads: list[str]) -> str:
        """Remove each literal '[payload]' once."""
        out = s
        for payload in bracket_payloads:
            out = out.replace(f"[{payload}]", "")
        return out

    def _strip_all_square_brackets(s: str) -> str:
        """Remove any [ ... ] segments (fallback pass)."""
        return re.sub(r"\[[^\]]*\]", "", s)

    def _strip_first_quoted_title(s: str) -> tuple[str, str | None]:
        """Remove the first quoted segment, returning (new_s, title_or_None)."""
        m = re.search(r'"(.*?)"', s)
        if not m:
            return s, None
        return s.replace(m.group(0), ""), m.group(1).strip() if m.group(1) else ""

    def _strip_first_parentheses_and_after(s: str) -> tuple[str, str | None, str]:
        """
        Remove the first '(...)' group; also return the post-date tail for publisher parsing.
        Returns (pre_date_text, date_raw_or_None, post_date_text).
        """
        m = re.search(r"\((.*?)\)", s)
        if not m:
            return s, None, ""
        pre = s[: m.start()].strip()
        date_raw = m.group(1).strip()
        post = s[m.end() :].strip()
        return pre, date_raw, post

    def _fallback_platform_from_original(src: str) -> str | None:
        """Derive a platform candidate from the original line by removing the comment 
        (outside quotes), all [..], quoted titles and (...) date, then trimming; return None if empty."""
        base, _comment = _split_comment_outside_quotes(src)
        base = _strip_all_square_brackets(base)
        base = re.sub(r'"[^"]*"', "", base)
        base = re.sub(r"\([^)]*\)", "", base)
        cand = base.strip()
        return cand or None


    # Anomaly counters: track likely quoting mistakes; exclude inch marks (3.5", 5.25").
    disk_quote_matches = re.findall(r'\b(?:3\.5|5\.25)"(?!\w)', working_line)
    quote_count = working_line.count('"') - len(disk_quote_matches)
    bracket_count = (working_line.count('(') + working_line.count(')') +
                     working_line.count('[') + working_line.count(']') +
                     working_line.count('{') + working_line.count('}'))
    if quote_count % 2 == 1:
        parsing_state.setdefault("odd_quotes", defaultdict(list))[system_name].append(working_line)
    if bracket_count % 2 == 1:
        parsing_state.setdefault("odd_brackets", defaultdict(list))[system_name].append(working_line)

    # 1) comment (outside quotes)
    working_line, comment = _split_comment_outside_quotes(working_line)
    if comment:
        port["comment"] = comment
        parsing_state["ports_with_comments"] += 1

    # 2) square brackets – including Model handling
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

    # remove only the exact bracket payloads we just processed
    working_line = _strip_square_brackets_exact_once(working_line, square_brackets)

    # 3) title – (first quoted)
    working_line, title = _strip_first_quoted_title(working_line)
    if title:
        port["title"] = title

    # 4) date (and publisher from tail)
    working_line, date_raw, post_date_text = _strip_first_parentheses_and_after(working_line)
    if date_raw:
        normalised_date = parse_date_string(date_raw, context=system_name)
        if normalised_date:
            port["date"] = normalised_date
        else:
            # Unrecognised date → keep original in residue and flag for summary.
            port["residue"].append(date_raw)
            parsing_state.setdefault("unparsable_dates", defaultdict(list))[system_name].append(date_raw)
            _mark_residue()

        # indicator counting only
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
            cleaned_pub = re.sub(r"^\s*by\s+", "", post_date_text, flags=re.IGNORECASE).strip()
            cleaned_pub = re.sub(r"^\s*-\s*", "", cleaned_pub)
            cleaned_pub = cleaned_pub.rstrip(".:; ")
            port["publisher"] = cleaned_pub
            publisher_data = parsing_state["publishers_found"][cleaned_pub]
            publisher_data["count"] += 1
            publisher_data["systems"].append(system_name)
    else:
        # no (date) → look for 'by ...' in the remaining text; count indicators
        if re.search(r"\breleased\s+by\b", working_line, flags=re.IGNORECASE):
            parsing_state["publisher_indicators_found"]["released_by"] += 1
        elif re.search(r"\bby\b", working_line, flags=re.IGNORECASE):
            parsing_state["publisher_indicators_found"]["by"] += 1
        else:
            parsing_state["publisher_indicators_found"]["none"] += 1

        match_pub = re.search(r"\bby\s+(.+)", working_line, flags=re.IGNORECASE)
        if match_pub:
            cleaned_pub = match_pub.group(1).strip()
            cleaned_pub = re.sub(r"^\s*-\s*", "", cleaned_pub)
            cleaned_pub = cleaned_pub.rstrip(".:; ")
            port["publisher"] = cleaned_pub
            publisher_data = parsing_state["publishers_found"][cleaned_pub]
            publisher_data["count"] += 1
            publisher_data["systems"].append(system_name)
            working_line = working_line[: match_pub.start()].strip()

    # 5) platform candidate from the *remaining* working_line (legacy path)
    platform_candidate = working_line.strip()

    # 5b) fallback — same step order reapplied to original_line, *only* if empty
    if not platform_candidate:
        platform_candidate = _fallback_platform_from_original(original_line)

    # 5c) assign & count
    if platform_candidate:
        port["platform"] = platform_candidate
        platforms = parsing_state.setdefault("platforms_found", defaultdict(lambda: {"count": 0, "systems": []}))
        platforms[platform_candidate]["count"] += 1
        platforms[platform_candidate]["systems"].append(system_name)

    # Track for additional summary
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

    Distinguishes arcade-relevant <systems> from <software>. Segments <text> into
    sections, extracts GH ID from CONTRIBUTE, and parses PORTS (including banner
    inheritance). Writes per-system JSON (gh_system_ports.json) and a rich summary
    (history_parsing_summary.json) covering totals, distributions, audits, and anomalies.

    Args:
      file_path: Path to history.xml.
      encoding: Text encoding to use when reading.

    Returns:
      True on success, False on XML parse error.

    Raises:
      None directly; errors are logged and a boolean is returned.

    Notes:
      - Uses ElementTree.iterparse to keep memory bounded.
      - Includes a set of invariants at the end which log warnings if counts drift
        (for example platform totals vs port line totals).
    """
    start = time.perf_counter()
    log.info(f"Parsing history.xml entries from: {file_path.name} using {encoding}")

    # Read <history> root attributes for the summary header
    history_version, history_date = None, None
    try:
        for event, elem in ET.iterparse(file_path, events=("start",)):
            if elem.tag.lower() == "history":
                history_version = elem.attrib.get("version")
                history_date = elem.attrib.get("date")
                break
    except ET.ParseError:
        log.warning("Could not read history root attributes for summary header")


    # ----------------------------
    # Parsing state (counters/maps)
    # ----------------------------
    parsing_state = {
        # Per-platform usage (by port row). Structure:
        # { platform: {"count": <occurrence_count>, "systems": [sys, ...]} }
        "platforms_found": defaultdict(lambda: {"count": 0, "systems": []}),

        # Publisher / platform / tag tracking
        "ports_with_comments": 0,
        "unparsable_dates": defaultdict(list),
        "systems_with_residue": set(),
        "section_headings_found": Counter(),
        "platform_categories_found": Counter(),
        "unexpected_platform_categories": defaultdict(list),
        "publishers_found": defaultdict(lambda: {"count": 0, "systems": []}),
        "publisher_indicators_found": {
            "released_by": 0,
            "by": 0,
            "other_after_date": 0,
            "none": 0
        },
        "odd_quotes": defaultdict(list),
        "odd_brackets": defaultdict(list),
        "titles_found": set(),
        "region_codes": Counter(),
        "models_found": defaultdict(list),
        "comments_found": defaultdict(list),
        "additional_tags_found": defaultdict(list),

        # For logging/inspection of overview texts in PORTS
        "systems_with_port_overview": {},

        # Banner detection (anomaly/audit, filled by extract_ports_section)
        "platform_banner_total": 0,
        "platform_banners_by_system": defaultdict(Counter),

        # Null platform after inheritance (anomaly, filled by extract_ports_section)
        "null_platform_ports_total": 0,
        "null_platform_ports_by_system": Counter(),
        "null_platform_examples": defaultdict(list),
        
        # Track disk-size quotes (3.5" / 5.25")
        "disk_size_quotes": defaultdict(list),  # { "3.5": [systems], "5.25": [systems], ... }
    }

    # ----------------------------
    # Totals
    # ----------------------------
    total_entries = 0
    systems_count = 0
    software_count = 0
    systems_with_ports = 0
    systems_with_aliases = 0
    port_overview_count = 0
    total_port_lines_all = 0

    # Parsed output
    gh_systems = {}

    # ----------------------------
    # Streaming parse of history.xml
    # ----------------------------
    try:
        with open(file_path, encoding=encoding) as f:
            for event, elem in ET.iterparse(f, events=("end",)):
                if elem.tag != "entry":
                    continue

                total_entries += 1
                
                if (total_entries % 10000) == 0:
                    log.info(f"[history_parser::parse_history_entries] Parsed {total_entries:,} entries so far...")                
                
                entry_data = {
                    "gh_id": None,
                    "aliases": [],
                    "port_overview": "",
                    "ports": {}
                }

                systems_elem = elem.find("systems")
                software_elem = elem.find("software")

                # Decide whether this entry is arcade-relevant (<systems>) or not (<software>)
                if systems_elem is not None:
                    systems_count += 1
                    system_names = [s.attrib.get("name")
                                    for s in systems_elem.findall("system")
                                    if s.attrib.get("name")]
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

                # TEXT parsing: split into sections; caller’s segment_text_sections must
                # preserve blank lines inside PORTS so banners can be detected reliably.
                text_elem = elem.find("text")
                if text_elem is not None and text_elem.text:
                    raw_text = html.unescape(text_elem.text)
                    sectioned = segment_text_sections(raw_text, parsing_state)

                    # CONTRIBUTE: pick up GH ID if present
                    if "CONTRIBUTE" in sectioned:
                        for line in sectioned["CONTRIBUTE"]:
                            m = re.search(r"id=(\d+)", line)
                            if m:
                                entry_data["gh_id"] = int(m.group(1))
                                break

                    # PORTS: main structured extraction
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

                        # Track category heading counts
                        if platform_counts:
                            for cat, c in platform_counts.items():
                                parsing_state["platform_categories_found"][cat] += c

                # Store per-system record
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
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "gh_system_ports.json"  # renamed

    # Stable diffs: sort system keys case-insensitively before writing JSON.
    systems_sorted = {k: gh_systems[k] for k in sorted(gh_systems.keys(), key=str.lower)}

    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(systems_sorted, f, indent=2, ensure_ascii=False)
        log.info(f"Saved parsed GH metadata (sorted) to {output_file} "
                 f"({len(systems_sorted)} systems)")
    except Exception as e:
        log.error(f"Failed to write GH systems JSON: {e}")


    # ----------------------------
    # Build summary JSON
    # ----------------------------
    # platforms_found — emit counts and deduped systems
    platforms_found_summary = {}
    for platform, data in parsing_state["platforms_found"].items():
        systems_unique = sorted(set(data["systems"]))
        platforms_found_summary[platform] = {
            "systems_count": len(systems_unique),
            "systems": systems_unique,
        }

    # For inspection and diff-friendliness: lists are deduped and A–Z sorted; maps A–Z sorted.
    _section_heads = dict(parsing_state["section_headings_found"])
    section_headings_block = {
        "unique": len(_section_heads),
        "distribution": dict(sorted(_section_heads.items(), key=lambda kv: kv[0].upper())),
    }

    # --- platform_categories_found: unique + distribution (A–Z) ---
    _cats = dict(parsing_state["platform_categories_found"])
    platform_categories_block = {
        "unique": len(_cats),
        "distribution": dict(sorted(_cats.items(), key=lambda kv: kv[0].upper())),
    }

    # --- platforms_found: unique + distribution (A–Z) + systems ---
    summary_platforms_block = {
        "unique": len(platforms_found_summary),
        "by_platform": dict(
            sorted(platforms_found_summary.items(), key=lambda kv: kv[0].lower())
        ),
    }

    # --- publishers_found: unique + by_publisher (systems view, A–Z) ---
    _publishers_map = parsing_state["publishers_found"]  # {name: {"count": N, "systems": [...]}}
    _by_publisher = {}
    for name, data in _publishers_map.items():
        systems_unique = sorted(set(data["systems"]))
        _by_publisher[name] = {
            "systems_count": len(systems_unique),
            "systems": systems_unique,
        }

    publishers_block = {
        "unique": len(_by_publisher),
        "indicators_found": {
            k: parsing_state["publisher_indicators_found"].get(k, 0)
            for k in ("by", "released_by", "other_after_date", "none")
        },
        "by_publisher": dict(sorted(_by_publisher.items(), key=lambda kv: kv[0].lower())),
    }

    # --- titles_found: unique + full items list (A–Z) ---
    titles_items = sorted(parsing_state["titles_found"])
    titles_block = {
        "unique": len(titles_items),
        "items": titles_items,
    }

    # --- region_codes: unique + distribution (by count desc, then A–Z) ---
    _region = parsing_state["region_codes"]  # Counter
    region_codes_block = {
        "unique": len(_region),
        "distribution": dict(sorted(_region.items(), key=lambda kv: (-kv[1], kv[0]))),
    }

    # --- models_found: unique + full items list (A–Z) ---
    models_items = sorted(parsing_state["models_found"].keys())
    models_block = {
        "unique": len(models_items),
        "items": models_items,
    }

    # --- comments_found: unique + by_comment (full, A–Z by comment text) ---
    _comments_map = parsing_state["comments_found"]  # {comment: [systems]}
    comments_block = {
        "unique": len(_comments_map),
        "by_comment": {
            comment: sorted(set(systems))
            for comment, systems in sorted(_comments_map.items(), key=lambda kv: kv[0].lower())
        },
    }

    # --- additional_tags_found: unique + by_tag (full, A–Z) ---
    _tags_map = parsing_state["additional_tags_found"]  # {tag: [systems]}
    additional_tags_block = {
        "unique": len(_tags_map),
        "by_tag": {
            tag: {
                "systems_count": len(set(systems)),
                "systems": sorted(set(systems)),
            }
            for tag, systems in sorted(_tags_map.items(), key=lambda kv: kv[0].lower())
        },
    }

    # --- port_overview_texts: count + full by_system map (A–Z) ---
    overviews_map = parsing_state["systems_with_port_overview"]  # {system: overview_text}
    port_overview_block = {
        "count": len(overviews_map),
        "by_system": dict(sorted(overviews_map.items(), key=lambda kv: kv[0].lower())),
    }

    # --- anomalies.unexpected_platform_categories: unique + by_category (full, A–Z) ---
    _upc_map = parsing_state["unexpected_platform_categories"]  # {category: [systems]}
    _by_category = {}
    systems_affected_set = set()

    for cat, systems in _upc_map.items():
        uniq_systems = sorted(set(systems))
        systems_affected_set.update(uniq_systems)
        _by_category[cat] = {
            "systems_count": len(uniq_systems),
            "systems": uniq_systems,
        }

    unexpected_platform_categories_block = {
        "unique": len(_by_category),
        "systems_affected": len(systems_affected_set),
        "by_category": dict(sorted(_by_category.items(), key=lambda kv: kv[0].lower())),
    }

    # --- anomalies.odd_number_of_quotes: count + by_system (full, A–Z) ---
    _oddq_map = parsing_state["odd_quotes"]  # {system: [offending lines]}
    odd_number_of_quotes_block = {
        "count": sum(len(lines) for lines in _oddq_map.values()),
        "systems_affected": len(_oddq_map),
        "by_system": {
            system: lines  # keep full lines verbatim; preserve parser order
            for system, lines in sorted(_oddq_map.items(), key=lambda kv: kv[0].lower())
        },
    }

    # --- anomalies.odd_number_of_brackets: count + by_system (full, A–Z) ---
    _oddb_map = parsing_state["odd_brackets"]  # {system: [offending lines]}
    odd_number_of_brackets_block = {
        "count": sum(len(lines) for lines in _oddb_map.values()),
        "systems_affected": len(_oddb_map),
        "by_system": {
            system: lines  # exhaustive, verbatim
            for system, lines in sorted(_oddb_map.items(), key=lambda kv: kv[0].lower())
        },
    }

    # --- anomalies.ports_missing_subheadings: count + by_system (excerpt, full set) ---
    _pms_list = parsing_state.get("anomalies", {}).get("ports_missing_subheadings", [])
    _pms_map = {}
    for rec in _pms_list:
        sys = rec.get("system")
        exc = rec.get("excerpt", "")
        if sys:
            _pms_map[sys] = exc

    ports_missing_subheadings_block = {
        "count": len(_pms_map),
        "by_system": dict(sorted(_pms_map.items(), key=lambda kv: kv[0].lower())),
    }

    # --- residue_flags.unparsable_dates: count + systems_affected + by_system (exhaustive) ---
    _ud_map = parsing_state["unparsable_dates"]  # {system: [bad_date_str, ...]}
    unparsable_dates_block = {
        "count": sum(len(v) for v in _ud_map.values()),
        "systems_affected": len(_ud_map),
        "by_system": {
            system: dates  # keep full lists verbatim
            for system, dates in sorted(_ud_map.items(), key=lambda kv: kv[0].lower())
        },
    }

    # --- residue_flags.systems_with_residue: count + items (full, A–Z) ---
    _swr_items = sorted(parsing_state["systems_with_residue"])
    systems_with_residue_block = {
        "count": len(_swr_items),
        "items": _swr_items,
    }

    _dsq = parsing_state["disk_size_quotes"]
    disk_size_quotes_block = {
        "unique": len(_dsq),
        "distribution": {
            size: {
                "count": len(set(systems)),
                "systems": sorted(set(systems)),
            }
            for size, systems in sorted(_dsq.items(), key=lambda kv: kv[0])
        },
    }

    summary = {
        "history": {
        "history_parser_schema": HISTORY_PARSER_SCHEMA,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "version": history_version,
        "date": history_date,
        },
        "totals": {
            "systems_total": systems_count,
            "software_total": software_count,
            "entries_total": systems_count + software_count,
            "systems_with_ports": systems_with_ports,
            "systems_with_aliases": systems_with_aliases,
            "port_lines_parsed": total_port_lines_all,
            "publisher_count_unique": len(parsing_state["publishers_found"]),
            "platform_count_unique": len(platforms_found_summary),
            "model_count_unique": len(models_items),
            "additional_tag_count_unique": additional_tags_block["unique"],
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
            "models_found": models_block,
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
                    sys: {
                        "count": sum(counter.values()),
                        "banners": dict(counter)
                    }
                    for sys, counter in sorted(parsing_state["platform_banners_by_system"].items())
                }
            },
            # Ports that still have null platform after inheritance (ideally 0)
            "null_platform_ports": {
                "count": parsing_state["null_platform_ports_total"],
                "systems_affected": len(parsing_state["null_platform_ports_by_system"]),
                "by_system": dict(sorted(
                    parsing_state["null_platform_ports_by_system"].items(),
                    key=lambda kv: (-kv[1], kv[0])
                )),
                "by_system_lines": {k: v for k, v in parsing_state["null_platform_examples"].items()}
            }
        },
        "residue_flags": {
            "unparsable_dates": unparsable_dates_block,
            "systems_with_residue": systems_with_residue_block,            
            
        },
    }

    summary_path = Path("data/history_parsing_summary.json")
    try:
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        debug_log(f"Wrote parsing summary to {summary_path}")
    except Exception as e:
        log.warning(f"Could not write parsing summary: {e}")

    log.info(f"History parsing completed in {time.perf_counter() - start:.2f} seconds")

    # --- Invariants (warnings only): detect drift between row-level counts and summary totals ---
    issues = 0
    def _warn_ok(cond: bool, msg: str):
        nonlocal issues
        if not cond:
            issues += 1
            log.warning(msg)

    # 1) Sanity: systems + software must equal the total number of <entry> elements parsed.
    _warn_ok(
        systems_count + software_count == total_entries,
        f"[history_parser] systems+software != total_entries ({systems_count}+{software_count}!={total_entries})"
    )

    # 2) Output cardinality: ensure we wrote exactly one gh_systems record per <systems> entry.
    _warn_ok(
        len(gh_systems) == systems_count,
        f"[history_parser] gh_systems record count {len(gh_systems)} != systems_count {systems_count}"
    )

    # 3) Sanity: platform hits plus null-platform rows must equal the number of parsed port lines.
    platform_occurrences = sum(d["count"] for d in parsing_state["platforms_found"].values())
    null_pl = parsing_state["null_platform_ports_total"]
    _warn_ok(
        platform_occurrences + null_pl == total_port_lines_all,
        "[history_parser] platforms_found + null_platforms = "
        f"{platform_occurrences} + {null_pl} != port_lines_parsed {total_port_lines_all} "
        "(see anomalies.platform_banners / null_platform_ports)"
    )

    # 4) Sanity: per-system null-platform sum must match the global null-platform total.
    _warn_ok(
        sum(parsing_state["null_platform_ports_by_system"].values()) == null_pl,
        "[history_parser] sum(null_platform_ports_by_system) != null_platform_ports_total"
    )

    # 5) Sanity: per-system banner counts must sum to the global banner total.
    banner_total_calc = sum(sum(c.values()) for c in parsing_state["platform_banners_by_system"].values())
    _warn_ok(
        banner_total_calc == parsing_state["platform_banner_total"],
        "[history_parser] platform_banner_total mismatch with by_system sum "
        f"({parsing_state['platform_banner_total']} != {banner_total_calc})"
    )

    # 6) Sanity limits: counts should not exceed their logical bounds.
    _warn_ok(
        systems_with_ports <= systems_count,
        f"[history_parser] systems_with_ports {systems_with_ports} > systems_count {systems_count}"
    )
    _warn_ok(
        port_overview_count <= systems_with_ports,
        f"[history_parser] port_overview_count {port_overview_count} > systems_with_ports {systems_with_ports}"
    )

    # 7) Soft check: any unexpected PORTS categories should be reported (information only).
    unknown_cats = [k for k in parsing_state["platform_categories_found"].keys()
                    if k.upper() not in KNOWN_PLATFORMS]
    if unknown_cats:
        log.info("[history_parser] unexpected PORTS categories encountered: %s", ", ".join(sorted(set(unknown_cats))))

    # 8) Residue values are coherent: systems_with_residue should at least cover unparsable_dates keys.
    _warn_ok(
        len(parsing_state.get("systems_with_residue", set())) >= len(parsing_state.get("unparsable_dates", {})),
        "[history_parser] systems_with_residue fewer than unparsable_dates keys"
    )

    if issues == 0:
        log.info("[history_parser] invariants passed")

    return True
