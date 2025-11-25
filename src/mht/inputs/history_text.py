from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Dict, List, Iterable, Optional
from difflib import get_close_matches
import html
import xml.etree.ElementTree as ET

from mht.inputs.history_constants import (
    STANDARD_SECTION_HEADERS,
    SECTION_ALIASES,
    normalise_section_heading,
)


__all__ = ["SECTION_PATTERN", "segment_text_sections"]

# ----- dashed headings like "----- PORTS -----" (case-insensitive)
SECTION_PATTERN = re.compile(r"^-+\s+([A-Z0-9 &]+)\s+-+$", re.IGNORECASE)
_GH_ID_RE = re.compile(r"id=(\d+)")

def _is_near_miss_banner(line: str) -> bool:
    """
    A "near-miss" banner is something that looks like -Foo-
    but is NOT a valid GH section banner.

    Rules:
    - Must start and end with a single ASCII '-' (not '--').
    - Must contain at least one alphabetical character inside.
    - Must NOT match SECTION_PATTERN (i.e., not a valid dashed heading).
    """
    if not line:
        return False
    # strip is already done by caller, but be defensive
    s = line.strip()
    if not (s.startswith('-') and s.endswith('-')):
        return False
    # reject crude separators like '---' / '-----' and multi-dash edges
    if s.startswith('--') or s.endswith('--'):
        return False
    # must contain at least one alphabetic character inside
    inner = s[1:-1]
    if not any(ch.isalpha() for ch in inner):
        return False
    # exclude true section banners
    if SECTION_PATTERN.match(s):
        return False
    return True

def _canonicalise_heading(raw_heading: str) -> tuple[str, dict]:
    """
    Return (canonical_heading, audit_info)
    - canonical_heading: one of STANDARD_SECTION_HEADERS (or the normalised original if unknown)
    - audit_info: details for anomaly recording
    """
    audit = {
        "raw": raw_heading,
        "normalised": None,
        "canonical": None,
        "mapped_via": None,   # 'alias' | 'fuzzy' | None
        "suggestion": None,
    }

    norm = normalise_section_heading(raw_heading)
    audit["normalised"] = norm

    if norm in STANDARD_SECTION_HEADERS:
        audit["canonical"] = norm
        return norm, audit

    if norm in SECTION_ALIASES:
        canon = SECTION_ALIASES[norm]
        audit["canonical"] = canon
        audit["mapped_via"] = "alias"
        audit["suggestion"] = canon
        return canon, audit

    # conservative fuzzy match; raise to 0.90 if you want to be stricter
    suggestion = next(iter(get_close_matches(norm, STANDARD_SECTION_HEADERS, n=1, cutoff=0.84)), None)
    if suggestion:
        audit["canonical"] = suggestion
        audit["mapped_via"] = "fuzzy"
        audit["suggestion"] = suggestion
        return suggestion, audit

    # Unknown/non-standard → keep as-is (still processed)
    audit["canonical"] = norm
    return norm, audit


def _record_heading_anomaly(parsing_state: dict, audit: dict, primary: str | None) -> None:
    """
    Record every non-standard/near-miss heading with ALL affected systems.
    """
    ns = parsing_state.setdefault("non_standard_sections", {})
    norm = audit["normalised"]
    canon = audit.get("canonical")
    via = audit.get("mapped_via")

    if norm in STANDARD_SECTION_HEADERS:
        return  # standard → nothing to record

    rec = ns.setdefault(norm, {"count": 0, "systems": set(), "mapped_to": None, "via": None})
    rec["count"] += 1
    if primary:
        rec["systems"].add(primary)
    if via:
        rec["mapped_to"] = canon
        rec["via"] = via

def segment_text_sections(text: str, parsing_state: Dict) -> Dict[str, List[str]]:
    """
    Split a GH <text> block into named sections; preserve blank lines only in PORTS.
    Mutates parsing_state['section_headings_found'] (Counter).
    """
    sections = defaultdict(list)
    current_section = "OVERVIEW"

    for raw in text.splitlines():
        norm = re.sub(r"\u00A0", " ", raw or "")
        line = norm.strip()

        # dashed section heading
        m = SECTION_PATTERN.match(line)
        if m:
            name = m.group(1).strip().upper()
            parsing_state.setdefault("section_headings_found", Counter())[name] += 1
            current_section = name
            continue

        if line == "":
            if current_section == "PORTS":
                sections[current_section].append("")  # keep separator for block detection
            continue

        sections[current_section].append(line)

    return sections

def parse_gh_id_from_contribute(lines: Iterable[str]) -> Optional[int]:
    """
    Given the lines from a CONTRIBUTE section, return the first gh_id found (as int),
    or None if no 'id=<int>' pattern exists.
    """
    for line in lines:
        m = _GH_ID_RE.search(line)
        if m:
            return int(m.group(1))
    return None

def extract_text_sections(elem: ET.Element, parsing_state: dict, primary: str | None = None) -> dict[str, list[str]]:
    """
    Split <text> into sections keyed by GH banners (dashed lines).
    Uses SECTION_PATTERN for valid headers and records near-miss banners for QA.
    Returns dict of section_name -> list of lines (not a single joined string).
    """
    text_node = elem.find("text")
    raw_text = text_node.text if (text_node is not None and text_node.text is not None) else ""
    raw_text = html.unescape(raw_text)

    current_section = "OPENING"   # preface until the first banner
    sections: dict[str, list[str]] = {current_section: []}

    for raw_line in raw_text.splitlines():
        # normalise NBSP and trim for matching; keep a trimmed line for content
        norm = re.sub(r"\u00A0", " ", raw_line or "")
        line = norm.strip()

        # Valid dashed heading (case-insensitive, spaces enforced)
        m = SECTION_PATTERN.match(line)
        if m:
            raw_banner = m.group(1).strip()
            canonical, audit = _canonicalise_heading(raw_banner)
            parsing_state.setdefault("section_headings_found", Counter())[canonical] += 1
            _record_heading_anomaly(parsing_state, audit, primary)
            current_section = canonical
            sections.setdefault(current_section, [])
            continue

        # Near-miss banners (e.g. -Option Menu-): log for QA only
        if _is_near_miss_banner(line):
            nsb = parsing_state.setdefault("banner_spacing_anomalies", {})
            nsb.setdefault(primary or "<unknown>", []).append(raw_line)

        # Blank lines: preserve in *all* sections so downstream block
        # classification can use them as paragraph/list separators.
        if line == "":
            sections[current_section].append("")  # keep separator everywhere
            continue

        # Normal content: append the trimmed line
        sections[current_section].append(line)

    return sections
        
def canonicalise_heading(raw_heading: str) -> tuple[str, dict]:
    """
    Return (canonical_heading, audit_info)
    - canonical_heading: one of STANDARD_SECTION_HEADERS or the normalised original if unknown
    - audit_info: dict describing mapping decisions to feed into parsing_state for the summary
    """
    audit = {
        "raw": raw_heading,
        "normalised": None,
        "canonical": None,
        "mapped_via": None,      # 'alias' | 'fuzzy' | None
        "suggestion": None       # fuzzy suggestion if used
    }

    norm = normalise_section_heading(raw_heading)
    audit["normalised"] = norm

    # Exact canonical
    if norm in STANDARD_SECTION_HEADERS:
        audit["canonical"] = norm
        return norm, audit

    # Alias map
    if norm in SECTION_ALIASES:
        canon = SECTION_ALIASES[norm]
        audit["canonical"] = canon
        audit["mapped_via"] = "alias"
        audit["suggestion"] = canon
        return canon, audit

    # Fuzzy: propose the closest canonical if very likely
    # Tweak cutoff as needed; 0.84 is conservative.
    suggestion = next(iter(get_close_matches(norm, STANDARD_SECTION_HEADERS, n=1, cutoff=0.84)), None)
    if suggestion:
        audit["canonical"] = suggestion
        audit["mapped_via"] = "fuzzy"
        audit["suggestion"] = suggestion
        return suggestion, audit

    # Unknown/non-standard → keep as-is (still processed), no mapping
    audit["canonical"] = norm
    return norm, audit
