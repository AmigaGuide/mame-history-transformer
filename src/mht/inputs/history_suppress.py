from __future__ import annotations

import re
from typing import Dict, List

__all__ = ["apply_suppressions"]

# Rules (first pass):
# - overview_type_line: suppress lines like "Arcade Video game published 45 years ago:"
# - overview_title_line: suppress lines like "Puckman (c) 1980 Namco." (or with ©)

_OVERVIEW_TYPE_RE   = re.compile(r"^\s*Arcade\s+Video\s+game\b", re.IGNORECASE)
_OVERVIEW_TITLE_RE1 = re.compile(r"^\s*.+?\(c\)\s*\d{4}\b.*$", re.IGNORECASE)
_OVERVIEW_TITLE_RE2 = re.compile(r"^\s*.+?[©]\s*\d{4}\b.*$", re.IGNORECASE)

def _record(parsing_state: Dict, system: str, section: str, rule: str, line: str) -> None:
    s = parsing_state.setdefault("suppressions", {})
    counts = s.setdefault("counts", {})
    counts[rule] = counts.get(rule, 0) + 1
    counts["total"] = counts.get("total", 0) + 1

    by_system = s.setdefault("by_system", {})
    lst = by_system.setdefault(system or "<unknown>", [])
    lst.append({"section": section, "rule": rule, "line": line})

def apply_suppressions(section_tag: str, lines: List[str], system: str, parsing_state: Dict) -> List[str]:
    """
    Apply section-specific suppression rules and record every suppression into parsing_state['suppressions'].

    Returns a new list of lines with suppressed lines removed.
    """
    if not lines:
        return lines

    out: List[str] = []

    if section_tag == "overview":
        for ln in lines:
            # Rule: overview_type_line
            if _OVERVIEW_TYPE_RE.match(ln):
                _record(parsing_state, system, "overview", "overview_type_line", ln)
                continue
            # Rule: overview_title_line (variants: (c) YEAR ...  or  © YEAR ...)
            if _OVERVIEW_TITLE_RE1.match(ln) or _OVERVIEW_TITLE_RE2.match(ln):
                _record(parsing_state, system, "overview", "overview_title_line", ln)
                continue
            out.append(ln)
        return out

    # No rules yet for other sections (future work: technical/soundtracks, etc.)
    return lines
