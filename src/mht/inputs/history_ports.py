from __future__ import annotations

from collections import Counter, defaultdict
import re

from mht.inputs.history_constants import (
    SECTION_PATTERN,
    CATEGORY_HEADING_PATTERN,
    KNOWN_PLATFORMS,
)
from mht.utils.date_utils import parse_date_string


__all__ = [
    "segment_text_sections",
    "extract_ports_section",
    "parse_port_entry",
]


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
