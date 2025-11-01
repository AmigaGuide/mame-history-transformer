from __future__ import annotations

import re
from typing import Dict, List

__all__ = ["apply_suppressions"]

# --------------------------
# Overview suppression rules
# --------------------------

# e.g. "Arcade Video game published 45 years ago:"
_OVERVIEW_TYPE_RE   = re.compile(r"^\s*Arcade\s+Video\s+game\b", re.IGNORECASE)

# e.g. "Puckman (c) 1980 Namco."  or  "Puckman © 1980 Namco."
_OVERVIEW_TITLE_RE1 = re.compile(r"^\s*.+?\(c\)\s*\d{4}\b.*$", re.IGNORECASE)
_OVERVIEW_TITLE_RE2 = re.compile(r"^\s*.+?[©]\s*\d{4}\b.*$", re.IGNORECASE)

# ----------------------------
# Technical suppression rules
# ----------------------------
# Suppress lines that duplicate MAME-provided facts:
#   - CPU / Main CPU
#   - Sound CPU
#   - Sound Chip(s)
#   - Players
#   - Control
#   - Buttons
#
# Heuristics are conservative and expect a colon-led field label (as GH usually does).

_TECH_CPU_RE         = re.compile(r"^\s*(?:main\s+)?cpus?\s*:", re.IGNORECASE)         # "Main CPU :", "CPU :", "CPUs :"
_TECH_SOUND_CPU_RE   = re.compile(r"^\s*(?:sound|audio)\s+cpus?\s*:", re.IGNORECASE)   # "Sound CPU :", "Sound CPUs :", "Audio CPU :"
_TECH_SOUND_RE       = re.compile(r"^\s*sound\s+chips?\s*:", re.IGNORECASE)            # "Sound Chips :", "Sound Chip :"
_TECH_PLAYERS_RE     = re.compile(r"^\s*players?\s*:", re.IGNORECASE)                  # "Players :", "Player :"
_TECH_CONTROL_RE     = re.compile(r"^\s*control\s*:", re.IGNORECASE)                   # "Control :"
_TECH_BUTTONS_RE     = re.compile(r"^\s*buttons?\s*:", re.IGNORECASE)                  # "Buttons :", "Button :"

def _record(parsing_state: Dict, system: str, section: str, rule: str, line: str) -> None:
    s = parsing_state.setdefault("suppressions", {})
    counts = s.setdefault("counts", {})
    counts[rule] = counts.get(rule, 0) + 1
    counts["total"] = counts.get("total", 0) + 1

    by_system = s.setdefault("by_system", {})
    lst = by_system.setdefault(system or "<unknown>", [])
    lst.append({"section": section, "rule": rule, "line": line})

def _apply_overview(lines: List[str], system: str, parsing_state: Dict) -> List[str]:
    out: List[str] = []
    for ln in lines:
        if _OVERVIEW_TYPE_RE.match(ln):
            _record(parsing_state, system, "overview", "overview_type_line", ln)
            continue
        if _OVERVIEW_TITLE_RE1.match(ln) or _OVERVIEW_TITLE_RE2.match(ln):
            _record(parsing_state, system, "overview", "overview_title_line", ln)
            continue
        out.append(ln)
    return out

def _apply_technical(lines: List[str], system: str, parsing_state: Dict) -> List[str]:
    out: List[str] = []
    for ln in lines:
        # Order is loosely grouped; patterns are mutually exclusive for well-formed GH lines.
        if _TECH_CPU_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_cpu_line", ln)
            continue
        if _TECH_SOUND_CPU_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_sound_cpu_line", ln)
            continue
        if _TECH_SOUND_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_sound_chips_line", ln)
            continue
        if _TECH_PLAYERS_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_players_line", ln)
            continue
        if _TECH_CONTROL_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_control_line", ln)
            continue
        if _TECH_BUTTONS_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_buttons_line", ln)
            continue
        out.append(ln)
    return out

def apply_suppressions(section_tag: str, lines: List[str], system: str, parsing_state: Dict) -> List[str]:
    """
    Apply section-specific suppression rules and record every suppression into parsing_state['suppressions'].

    Parameters
    ----------
    section_tag : str
        Lower-case tag used by the parser (e.g., 'overview', 'technical', 'trivia', 'updates', etc.)
    lines : List[str]
        Section lines (unjoined).
    system : str
        Primary MAME/GH system name (for audit).
    parsing_state : Dict
        Mutable state for accumulating suppression counts and examples.

    Returns
    -------
    List[str]
        Lines with suppressed content removed.
    """
    if not lines:
        return lines

    if section_tag == "overview":
        return _apply_overview(lines, system, parsing_state)

    if section_tag == "technical":
        return _apply_technical(lines, system, parsing_state)

    # No active rules for other sections yet.
    return lines
