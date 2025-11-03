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
# Label-style fields (with colon) that duplicate MAME-provided facts
_TECH_CPU_RE             = re.compile(r"^\s*(?:main\s+)?cpus?\s*:", re.IGNORECASE)            # "Main CPU :", "CPU :", "CPUs :"
_TECH_SOUND_CPU_RE       = re.compile(r"^\s*(?:sound|audio)\s+cpus?\s*:", re.IGNORECASE)      # "Sound CPU :", "Audio CPU :"
_TECH_SOUND_RE           = re.compile(r"^\s*sound\s+chips?\s*:", re.IGNORECASE)               # "Sound Chips :", "Sound Chip :"
_TECH_PLAYERS_RE         = re.compile(r"^\s*players?\s*:", re.IGNORECASE)                     # "Players :", "Player :"
_TECH_CONTROL_RE         = re.compile(r"^\s*control\s*:", re.IGNORECASE)                      # "Control :"
_TECH_BUTTONS_RE         = re.compile(r"^\s*buttons?\s*:", re.IGNORECASE)                     # "Buttons :", "Button :"

_TECH_SCREEN_ORIENT_RE   = re.compile(r"^\s*screen\s+orientation\s*:", re.IGNORECASE)         # "Screen Orientation :"
_TECH_SCREEN_RES_RE      = re.compile(r"^\s*screen\s+resolution\s*:", re.IGNORECASE)          # "Screen Resolution :"
_TECH_VIDEO_RES_RE       = re.compile(r"^\s*video\s+resolution\s*:", re.IGNORECASE)           # "Video resolution :"
_TECH_REFRESH_RATE_RE    = re.compile(r"^\s*refresh\s+rate\s*:", re.IGNORECASE)               # "Refresh Rate :"
_TECH_SCREEN_REFRESH_RE  = re.compile(r"^\s*screen\s+refresh\s*:", re.IGNORECASE)             # "Screen refresh :"
_TECH_PALETTE_COLOURS_RE = re.compile(r"^\s*palette\s+colou?rs?\s*:", re.IGNORECASE)          # "Palette colours :", "Palette colors :"

# Pair-style fields: allow ":" OR "-" as the separator (GH sometimes uses hyphens)
_PAIR_SEP = r"\s*(?::|-)\s*"
_TECH_BUTTONS_PAIR_RE     = re.compile(rf"^\s*(?:buttons?(?:\s+per\s+player)?|controls?)({_PAIR_SEP}).+$", re.IGNORECASE)
_TECH_CONTROL_PER_PLAYER  = re.compile(rf"^\s*controls?\s+per\s+player{_PAIR_SEP}.+$", re.IGNORECASE)
_TECH_GAME_SIZE_RE        = re.compile(rf"^\s*game\s+size{_PAIR_SEP}.+$", re.IGNORECASE)
_TECH_DISPLAY_PAIR_RE     = re.compile(rf"^\s*display{_PAIR_SEP}.+$", re.IGNORECASE)

# Control mapping lines (free-form), e.g. "=> [A] FIRE, [B] SPECIAL"
_TECH_CONTROL_MAP_RE      = re.compile(r"^\s*=>\s*\[[^\]]+\].*$")

# Narrative/spec-style heuristics (TECHNICAL section only)
# Keep these as content detectors (not label-led), since GH often writes prose lines.
_HW_FREQUENCY_RE   = re.compile(r"\b\d+(?:\.\d+)?\s*(?:m|k)?\s*hz\b", re.IGNORECASE)          # "3.58MHz", "60 Hz", "15.7 kHz"
_HW_PROCESSOR_RE   = re.compile(r"\b(?:co-?\s*)?processor\b", re.IGNORECASE)                  # "processor", "co-processor"
# Treat DAC/DMA as audio-IC spec; include common IC acronyms in chipset group
_HW_CHIPSET_RE     = re.compile(r"\bchipset\b|\b(?:gpu|ppu|vdp|mcu)\b|\bdac\b|\bdma\b", re.IGNORECASE)
# Memory variants — exclude ROM per your preference
_HW_MEMORY_RE      = re.compile(r"\b(?:memory|ram|sram|dram|vram)\b", re.IGNORECASE)

# Inline helpers for specific content within pairs
_N_WAY_JOYSTICK_RE = re.compile(r"\b\d+\s*[-]?\s*way\b.*\bjoystick\b", re.IGNORECASE)         # "4-way joystick", "8 way joystick"
_RESOLUTION_INLINE_RE = re.compile(r"\b\d{2,4}\s*x\s*\d{2,4}\b|\bresolution\b", re.IGNORECASE)
_COLOURS_INLINE_RE    = re.compile(r"\bcolou?rs?\b", re.IGNORECASE)

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
        # Label-led fields (colon)
        if _TECH_CPU_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_cpu_line", ln);               continue
        if _TECH_SOUND_CPU_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_sound_cpu_line", ln);         continue
        if _TECH_SOUND_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_sound_chips_line", ln);       continue
        if _TECH_PLAYERS_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_players_line", ln);           continue
        if _TECH_CONTROL_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_control_line", ln);           continue
        if _TECH_BUTTONS_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_buttons_line", ln);           continue
        if _TECH_SCREEN_ORIENT_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_screen_orientation_line", ln);  continue
        if _TECH_SCREEN_RES_RE.match(ln) or _TECH_VIDEO_RES_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_screen_resolution_line", ln);   continue
        if _TECH_REFRESH_RATE_RE.match(ln) or _TECH_SCREEN_REFRESH_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_refresh_rate_line", ln);        continue
        if _TECH_PALETTE_COLOURS_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_palette_colours_line", ln);     continue

        # Pair-led fields (colon OR hyphen separators)
        if _TECH_BUTTONS_PAIR_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_buttons_pair_line", ln);        continue
        if _TECH_CONTROL_PER_PLAYER.match(ln):
            _record(parsing_state, system, "technical", "technical_control_per_player_line", ln);  continue
        if _TECH_GAME_SIZE_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_game_size_line", ln);           continue
        if _TECH_DISPLAY_PAIR_RE.match(ln):
            # Be explicit about which aspects we saw for audit
            if _RESOLUTION_INLINE_RE.search(ln):
                _record(parsing_state, system, "technical", "technical_display_resolution_line", ln)
                continue
            if _COLOURS_INLINE_RE.search(ln):
                _record(parsing_state, system, "technical", "technical_display_colours_line", ln)
                continue
            # If neither keyword found, still treat generic Display pair as technical display
            _record(parsing_state, system, "technical", "technical_display_line", ln)
            continue

        # Free-form control mappings, e.g. "=> [A] FIRE, [B] SPECIAL"
        if _TECH_CONTROL_MAP_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_control_mapping_line", ln);     continue

        # Narrative/spec style lines (heuristics)
        if _HW_PROCESSOR_RE.search(ln):
            _record(parsing_state, system, "technical", "technical_processor_line", ln);           continue
        if _HW_CHIPSET_RE.search(ln):
            _record(parsing_state, system, "technical", "technical_chipset_line", ln);             continue
        if _HW_FREQUENCY_RE.search(ln):
            _record(parsing_state, system, "technical", "technical_frequency_line", ln);           continue
        if _HW_MEMORY_RE.search(ln):
            _record(parsing_state, system, "technical", "technical_memory_line", ln);              continue

        # Joystick n-way heuristics (e.g. "4-way joystick")
        if _N_WAY_JOYSTICK_RE.search(ln):
            _record(parsing_state, system, "technical", "technical_joystick_n_way_line", ln);      continue

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
