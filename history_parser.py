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

Output is saved to output/gh_systems.json and used to support ExoticA's
Lost in Translation (LiT) Wiki metadata.

This file is part of a student project and is not intended for commercial use.
"""

# UPDATED history_parser.py to include extended summary tracking within existing structure

from pathlib import Path
import xml.etree.ElementTree as ET
import time
import re
import json
import html
from collections import Counter, defaultdict, OrderedDict
import datetime

from config import LOG_LEVEL
from logger import setup_logger, debug_log
from date_utils import parse_date_string

log = setup_logger(log_level=LOG_LEVEL)

HISTORY_PARSER_SCHEMA = "1.0"
SECTION_PATTERN = re.compile(r"^-+\s+([A-Z0-9 &]+)\s+-+$", re.IGNORECASE)
CATEGORY_HEADING_PATTERN = re.compile(r"^\*\s*([A-Z0-9 &]+)\s*:\s*$", re.IGNORECASE)
KNOWN_PLATFORMS = {"CONSOLES", "COMPUTERS", "HANDHELDS", "OTHERS"}

def is_odd(n):
    return n % 2 == 1

def segment_text_sections(text: str, parsing_state: dict) -> dict:
    sections = defaultdict(list)
    current_section = "OVERVIEW"

    for raw in text.splitlines():
        # normalise NBSP → space, then strip to test emptiness
        norm = re.sub(r"\u00A0", " ", raw or "")
        line = norm.strip()

        # Section heading like '----- PORTS -----'
        match = SECTION_PATTERN.match(line)
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


def extract_ports_section(lines: list[str], system_name: str, parsing_state: dict) -> tuple[str, Counter, dict, int]:
    """
    Parse a PORTS block:
      - Build overview (pre-category text).
      - Count category headings (CONSOLES/COMPUTERS/HANDHELDS/OTHERS).
      - Detect 'platform banner' ONLY when:
          • it is the first non-empty line after a category heading OR a truly blank line, AND
          • the very next non-empty line is 'portish' (contains quotes or [] or () or a colon), AND
          • the candidate itself has no quotes/parentheses/colon and DOES NOT start with '['.
            (Bracket qualifiers such as 'Sony PS3 [PSN]' are allowed if not leading.)
        Banners are recorded under anomalies and used to INHERIT platform into following port rows.
      - All other non-empty lines under a recognised category are parsed as port rows.
      - Returns (overview, platform_counter, platform_entries, total_port_lines).
    """
    # Ensure anomaly trackers & new null-platform trackers exist
    if "platform_banner_total" not in parsing_state:
        parsing_state["platform_banner_total"] = 0
    if "platform_banners_by_system" not in parsing_state:
        parsing_state["platform_banners_by_system"] = defaultdict(Counter)

    parsing_state.setdefault("null_platform_ports_total", 0)
    parsing_state.setdefault("null_platform_ports_by_system", Counter())
    parsing_state.setdefault("null_platform_examples", defaultdict(list))

    def _norm(s: str) -> str:
        """
        Normalise a single line of text for PORTS parsing.

        - Converts non-breaking spaces (U+00A0) to a regular space so visually blank
          lines become truly blank after stripping.
        - Strips leading and trailing whitespace only (internal spacing is preserved).
        - Treats None as an empty string.

        This is used to make blank-line separators in the PORTS section reliable even
        when the source uses NBSPs.

        Examples
        --------
        >>> _norm(None)
        ''
        >>> _norm('\\u00A0\\u00A0')  # two NBSPs
        ''
        >>> _norm('Foo\\u00A0Bar ')
        'Foo Bar'
        """
        if s is None:
            return ""
        return s.replace("\u00A0", " ").strip()

    def _is_portish(s: str) -> bool:
        """
        Heuristic: does a line *look* like a concrete PORT entry?

        After normalisation via _norm(), returns True if the line contains any of:
        - a double-quoted title:        '"'
        - region/model square brackets: '[' or ']'
        - a parenthesised date:         '(' or ')'
        - a colon separator:            ':'   (e.g. 'Atari 2600: Release cancelled')

        These markers are characteristic of Gaming-History port rows (region/date/
        title/publisher notes). Banner lines should lack all of them.

        Notes
        -----
        - Empty or whitespace-only lines return False.
        - This is a lightweight shape check; it does not validate syntax.

        Examples
        --------
        >>> _is_portish('[EU] (1993) "Mortal Kombat [Model T-81186-50]"')
        True
        >>> _is_portish('Atari 2600: Release cancelled')
        True
        >>> _is_portish('Sega Mega Drive / Genesis')
        False
        >>> _is_portish('')  # or None via _norm in the caller
        False
        """
        t = _norm(s)
        if not t:
            return False
        return ('"' in t) or ('[' in t) or (']' in t) or ('(' in t) or (')' in t) or (':' in t)

    def _looks_like_banner_text(s: str) -> bool:
        """
        Banner shape:
          - NOT starting with '[' (leading region/tag means it's a port)
          - No quotes/parens/colon anywhere (ports have those)
          - Bracket qualifiers allowed ONLY if not leading (e.g. 'Sony PS3 [PSN]')
          - Must contain letters after stripping trailing/inline brackets for the letter check
        """
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
    platform_counter: Counter = Counter()         # counts of KNOWN_PLATFORMS headings seen
    platform_entries: dict[str, list[dict]] = {}  # {category -> [parsed_entry, ...]}
    current_category: str | None = None           # category: CONSOLES/COMPUTERS/...
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
                # Confirmed banner: record and set context; do not count as a port row
                parsing_state["platform_banner_total"] += 1
                parsing_state["platform_banners_by_system"][system_name][line] += 1
                platform_ctx = line
                at_block_start = False
                i += 1
                continue
            # else: treat this line as a sparse/ambiguous port row (fall through)

        # Otherwise, treat as a real port row
        if current_category:
            parsed_entry = parse_port_entry(line, system_name=system_name, parsing_state=parsing_state)

            # INHERIT: if no inline platform, use current banner context
            inherited = False
            if not parsed_entry.get("platform") and platform_ctx:
                parsed_entry["platform"] = platform_ctx
                inherited = True
                # reflect in platforms_found (avoid double counting inline platform cases)
                platforms = parsing_state.setdefault(
                    "platforms_found", defaultdict(lambda: {"count": 0, "systems": []})
                )
                platforms[platform_ctx]["count"] += 1
                platforms[platform_ctx]["systems"].append(system_name)

            # If still no platform, record a null-platform anomaly
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
        preview = " ".join(overview_lines).strip()
        (parsing_state.setdefault("anomalies", {})
                      .setdefault("ports_missing_subheadings", []))
        parsing_state["anomalies"]["ports_missing_subheadings"].append({
            "system": system_name,
            "preview": preview[:140]
        })

    return overview, platform_counter, platform_entries, total_port_lines


def parse_port_entry(line: str, system_name: str = "", parsing_state: dict = None) -> dict:
    """
    Parse a single PORTS line into a structured record.
    Behaviour matches legacy logic; adds a platform *fallback* that reuses the same
    strip steps in the same order when the primary working_line becomes empty.
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

    # --- helpers (local; order-matched) ---------------------------------------
    def _split_comment_outside_quotes(s: str) -> tuple[str, str | None]:
        """Split on the first ':' not inside double quotes. Return (before, comment_or_None)."""
        idx = -1
        in_quotes = False
        for i, ch in enumerate(s):
            if ch == '"':
                in_quotes = not in_quotes
            elif ch == ':' and not in_quotes:
                idx = i
                break
        if idx != -1:
            return s[:idx].rstrip(), s[idx + 1 :].strip()
        return s, None

    def _strip_square_brackets_exact_once(s: str, bracket_payloads: list[str]) -> str:
        """Remove each literal '[payload]' once (mirrors your existing replacements)."""
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
        """
        Derive platform from the original line using the SAME step order:
          1) split comment at colon (outside quotes),
          2) strip all [ ... ],
          3) strip all " ... ",
          4) strip all ( ... ),
          5) trim.
        """
        base, _comment = _split_comment_outside_quotes(src)
        base = _strip_all_square_brackets(base)
        base = re.sub(r'"[^"]*"', "", base)
        base = re.sub(r"\([^)]*\)", "", base)
        cand = base.strip()
        return cand or None
    # --------------------------------------------------------------------------

    # Count odd quotes / brackets (unchanged)
    disk_quote_matches = re.findall(r'\b(?:3\.5|5\.25)"(?!\w)', working_line)
    quote_count = working_line.count('"') - len(disk_quote_matches)
    bracket_count = (working_line.count('(') + working_line.count(')') +
                     working_line.count('[') + working_line.count(']') +
                     working_line.count('{') + working_line.count('}'))
    if quote_count % 2 == 1:
        parsing_state.setdefault("odd_quotes", defaultdict(list))[system_name].append(working_line)
    if bracket_count % 2 == 1:
        parsing_state.setdefault("odd_brackets", defaultdict(list))[system_name].append(working_line)

    # 1) comment (outside quotes) – identical logic
    working_line, comment = _split_comment_outside_quotes(working_line)
    if comment:
        port["comment"] = comment
        parsing_state["ports_with_comments"] += 1

    # 2) square brackets – identical behaviour including Model handling
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

    # remove only the exact bracket payloads we just processed (as before)
    working_line = _strip_square_brackets_exact_once(working_line, square_brackets)

    # 3) title – identical behaviour (first quoted)
    working_line, title = _strip_first_quoted_title(working_line)
    if title:
        port["title"] = title

    # 4) date (and publisher from tail) – identical behaviour
    working_line, date_raw, post_date_text = _strip_first_parentheses_and_after(working_line)
    if date_raw:
        normalised_date = parse_date_string(date_raw, context=system_name)
        if normalised_date:
            port["date"] = normalised_date
        else:
            port["residue"].append(date_raw)
            parsing_state.setdefault("unparsable_dates", defaultdict(list))[system_name].append(date_raw)

        # indicator counting only (unchanged)
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
        # no (date) → look for 'by ...' in the remaining text; count indicators (unchanged)
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

    # 5c) assign & count (unchanged)
    if platform_candidate:
        port["platform"] = platform_candidate
        platforms = parsing_state.setdefault("platforms_found", defaultdict(lambda: {"count": 0, "systems": []}))
        platforms[platform_candidate]["count"] += 1
        platforms[platform_candidate]["systems"].append(system_name)

    # Track for additional summary (unchanged)
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


def parse_history_entries(file_path: Path, encoding: str) -> dict:
    """
    Parse history.xml <entry> blocks into `output/gh_systems.json` and emit a rich
    summary to `data/history_parsing_summary.json`.

    Behaviour:
    - Splits <text> into sections (caller’s segment_text_sections should preserve blank
      lines inside PORTS so banner detection can work).
    - Distinguishes <systems> (arcade-relevant) vs <software> (skipped).
    - Extracts GH ID from the CONTRIBUTE section when present.
    - Parses PORTS with extract_ports_section():
        * Builds an overview paragraph (pre-category).
        * Collects per-category port rows (with banner inheritance applied inside
          extract_ports_section).
        * Tracks platform banners (anomaly/audit) and null-platform ports (anomaly).
    - Gathers various counters (publishers, platforms, titles, region codes, models, etc.).
    - Writes:
        * output/gh_systems.json    — per-system parsed record
        * data/history_parsing_summary.json — totals + “found” + anomalies

    Returns:
        True on success; False on XML parse error.
    """
    start = time.perf_counter()
    log.info(f"Parsing history.xml entries from: {file_path.name} using {encoding}")

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
    # Write parsed per-system output
    # ----------------------------
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "gh_systems.json"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(gh_systems, f, indent=2, ensure_ascii=False)
        log.info(f"Saved parsed GH metadata to {output_file}")
    except Exception as e:
        log.error(f"Failed to write GH entries JSON: {e}")

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

    summary = {
        "totals": {
            "systems_total": systems_count,
            "software_total": software_count,
            "entries_total": systems_count + software_count,
            "systems_with_ports": systems_with_ports,
            "systems_with_aliases": systems_with_aliases,
            "port_lines_parsed": total_port_lines_all,
            "publisher_count_unique": len(parsing_state["publishers_found"]),
            "platform_count_unique": len(platforms_found_summary),
            "ports_with_comments": parsing_state["ports_with_comments"],
        },
        "found": {
            "section_headings_found": dict(parsing_state["section_headings_found"]),
            "platform_categories_found": dict(parsing_state["platform_categories_found"]),           
            "platforms_found": dict(
                sorted(platforms_found_summary.items(), key=lambda kv: kv[0].lower())
            ),
            "publishers_found": {
                "indicators_found": {
                    k: parsing_state["publisher_indicators_found"].get(k, 0)
                    for k in ("by", "released_by", "other_after_date", "none")
                },
                "publishers": dict(sorted(parsing_state["publishers_found"].items()))
            },
            "titles_found": sorted(parsing_state["titles_found"]),
            "region_codes": dict(sorted(parsing_state["region_codes"].items(), key=lambda x: x[1], reverse=True)),
            "models_found": {
                model: sorted(set(systems))
                for model, systems in sorted(parsing_state["models_found"].items())
            },
            "comments_found": {
                "count": len(parsing_state["comments_found"]),
                "examples": dict(sorted(parsing_state["comments_found"].items()))
            },
            "additional_tags_found": {
                tag: sorted(set(systems))
                for tag, systems in sorted(parsing_state["additional_tags_found"].items())
            },
            "port_overview_texts": {
                "count": len(parsing_state["systems_with_port_overview"]),
                "examples": parsing_state["systems_with_port_overview"]
            },
        },
        "anomalies": {
            # Unexpected category headings under PORTS
            "unexpected_platform_categories": {
                k: sorted(v) for k, v in sorted(parsing_state["unexpected_platform_categories"].items())
            },
            # Non-matching quotes/brackets (shape issues)
            "odd_quotes": {k: v for k, v in sorted(parsing_state["odd_quotes"].items())},
            "odd_brackets": {k: v for k, v in sorted(parsing_state["odd_brackets"].items())},

            # PORTS present but no recognised subheadings
            "ports_missing_subheadings": {
                "count": len(parsing_state.get("anomalies", {}).get("ports_missing_subheadings", [])),
                "examples": parsing_state.get("anomalies", {}).get("ports_missing_subheadings", [])[:25]
            },

            # Banner lines (audit trail)
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

            # Ports that still had null platform after inheritance (ideally 0)
            "null_platform_ports": {
                "count": parsing_state["null_platform_ports_total"],
                "systems_affected": len(parsing_state["null_platform_ports_by_system"]),
                "by_system": dict(sorted(
                    parsing_state["null_platform_ports_by_system"].items(),
                    key=lambda kv: (-kv[1], kv[0])
                )),
                "examples": {k: v for k, v in parsing_state["null_platform_examples"].items()}
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


    # --- INVARIANTS & CONSISTENCY CHECKS (warnings only) -------------------------
    issues = 0
    def _warn_ok(cond: bool, msg: str):
        nonlocal issues
        if not cond:
            issues += 1
            log.warning(msg)

    # 1) Entry accounting
    _warn_ok(
        systems_count + software_count == total_entries,
        f"[history_parser] systems+software != total_entries ({systems_count}+{software_count}!={total_entries})"
    )

    # 2) Output cardinality
    _warn_ok(
        len(gh_systems) == systems_count,
        f"[history_parser] gh_systems record count {len(gh_systems)} != systems_count {systems_count}"
    )

    # 3) Platform usage counts should cover all parsed port lines (inline + inherited + null)
    platform_occurrences = sum(d["count"] for d in parsing_state["platforms_found"].values())
    null_pl = parsing_state["null_platform_ports_total"]
    _warn_ok(
        platform_occurrences + null_pl == total_port_lines_all,
        "[history_parser] platforms_found + null_platforms = "
        f"{platform_occurrences} + {null_pl} != port_lines_parsed {total_port_lines_all} "
        "(see anomalies.platform_banners / null_platform_ports)"
    )

    # 4) Null-platform: per-system sum matches total
    _warn_ok(
        sum(parsing_state["null_platform_ports_by_system"].values()) == null_pl,
        "[history_parser] sum(null_platform_ports_by_system) != null_platform_ports_total"
    )

    # 5) Banner totals: per-system sum matches global
    banner_total_calc = sum(sum(c.values()) for c in parsing_state["platform_banners_by_system"].values())
    _warn_ok(
        banner_total_calc == parsing_state["platform_banner_total"],
        "[history_parser] platform_banner_total mismatch with by_system sum "
        f"({parsing_state['platform_banner_total']} != {banner_total_calc})"
    )

    # 6) Sanity limits
    _warn_ok(
        systems_with_ports <= systems_count,
        f"[history_parser] systems_with_ports {systems_with_ports} > systems_count {systems_count}"
    )
    _warn_ok(
        port_overview_count <= systems_with_ports,
        f"[history_parser] port_overview_count {port_overview_count} > systems_with_ports {systems_with_ports}"
    )

    # 7) PORTS category headings are within the expected set (soft check)
    unknown_cats = [k for k in parsing_state["platform_categories_found"].keys()
                    if k.upper() not in KNOWN_PLATFORMS]
    if unknown_cats:
        log.info("[history_parser] unexpected PORTS categories encountered: %s", ", ".join(sorted(set(unknown_cats))))

    if issues == 0:
        log.info("[history_parser] invariants passed")


    return True
