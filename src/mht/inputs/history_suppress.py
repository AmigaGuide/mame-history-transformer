from __future__ import annotations

import re
from typing import List, Tuple, Dict, Any

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

# Inline helpers for specific content within pairs
_RESOLUTION_INLINE_RE = re.compile(r"\b\d{2,4}\s*x\s*\d{2,4}\b|\bresolution\b", re.IGNORECASE)
_COLOURS_INLINE_RE    = re.compile(r"\bcolou?rs?\b", re.IGNORECASE)

# (Deliberately NOT used for suppression any more — narrative paragraphs must survive)
# _HW_FREQUENCY_RE   = re.compile(r"\b\d+(?:\.\d+)?\s*(?:m|k)?\s*hz\b", re.IGNORECASE)
# _HW_PROCESSOR_RE   = re.compile(r"\b(?:co-?\s*)?processor\b", re.IGNORECASE)
# _HW_CHIPSET_RE     = re.compile(r"\bchipset\b|\b(?:gpu|ppu|vdp|mcu)\b|\bdac\b|\bdma\b", re.IGNORECASE)
# _HW_MEMORY_RE      = re.compile(r"\b(?:memory|ram|sram|dram|vram)\b", re.IGNORECASE)

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
        # Preserve paragraph separators
        if not (ln or "").strip():
            out.append("")
            continue

        if _OVERVIEW_TYPE_RE.match(ln):
            _record(parsing_state, system, "overview", "overview_type_line", ln)
            continue
        if _OVERVIEW_TITLE_RE1.match(ln) or _OVERVIEW_TITLE_RE2.match(ln):
            _record(parsing_state, system, "overview", "overview_title_line", ln)
            continue

        out.append(ln)
    return out

def _apply_technical(lines: List[str], system: str, parsing_state: Dict) -> List[str]:
    """
    IMPORTANT: Only suppress explicit labels/pairs/mappings.
    DO NOT suppress narrative paragraphs containing generic words (processor, MHz, RAM, etc.).
    """
    out: List[str] = []
    for ln in lines:
        if not (ln or "").strip():
            out.append("")
            continue

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

        # Pair-led fields (':' or '-')
        if _TECH_BUTTONS_PAIR_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_buttons_pair_line", ln);        continue
        if _TECH_CONTROL_PER_PLAYER.match(ln):
            _record(parsing_state, system, "technical", "technical_control_per_player_line", ln);  continue
        if _TECH_GAME_SIZE_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_game_size_line", ln);           continue
        if _TECH_DISPLAY_PAIR_RE.match(ln):
            if _RESOLUTION_INLINE_RE.search(ln):
                _record(parsing_state, system, "technical", "technical_display_resolution_line", ln)
                continue
            if _COLOURS_INLINE_RE.search(ln):
                _record(parsing_state, system, "technical", "technical_display_colours_line", ln)
                continue
            _record(parsing_state, system, "technical", "technical_display_line", ln)
            continue

        # Free-form control mappings
        if _TECH_CONTROL_MAP_RE.match(ln):
            _record(parsing_state, system, "technical", "technical_control_mapping_line", ln);     continue

        # NOTE: We intentionally do NOT suppress narrative/spec heuristics anymore.
        # e.g., lines containing "processor", "MHz", "memory" etc. are kept unless they match label/pair patterns.

        out.append(ln)
    return out

def _first_content_paragraph(raw_lines: List[str]) -> str | None:
    """
    Heuristic to detect a 'content-looking' paragraph:
    - first non-blank line with either:
      * length >= 100 characters, or
      * >= 12 words, or
      * contains at least two sentence separators among . , ; :
    """
    for raw in raw_lines:
        line = (raw or "").strip()
        if not line:
            continue
        if len(line) >= 100:
            return raw
        if len(line.split()) >= 12:
            return raw
        seps = sum(ch in line for ch in ".,;:")
        if seps >= 2:
            return raw
    return None

def apply_suppressions(
    section_tag: str,
    raw_lines: List[str],
    primary: str,
    parsing_state: Dict[str, Any]
) -> Tuple[List[str], Dict[str, Any]]:
    """
    Filter lines for a given section and record per-line provenance.

    Returns:
        filtered_lines: list[str]  (lines that survived)
        prov: {
            "raw_line_indices": List[int],        # 1-based raw line number for each filtered line
            "line_suppressions": Dict[int, List[str]]  # filtered idx -> suppression keys applied on that kept line
        }
    """
    filtered: List[str] = []
    raw_to_filtered_idx: List[int] = []
    line_suppressions: Dict[int, List[str]] = {}

    def keep(raw_idx: int, text: str, suppress_keys: List[str]) -> None:
        filtered.append(text)
        raw_to_filtered_idx.append(raw_idx)
        if suppress_keys:
            line_suppressions[len(filtered) - 1] = list(suppress_keys)

    tag = (section_tag or "").strip().lower()

    if tag == "overview":
        kept = _apply_overview(raw_lines, primary, parsing_state)

        # Fail-open: if original had content but everything got stripped, restore the first content-looking paragraph.
        non_empty_original = any((ln or "").strip() for ln in raw_lines)
        non_empty_kept     = any((ln or "").strip() for ln in kept)
        if non_empty_original and not non_empty_kept:
            first_para = _first_content_paragraph(raw_lines)
            if first_para:
                kept = [first_para]

        # Rebuild provenance using a two-pointer walk (preserves order after drops).
        ki = 0
        for i, ln in enumerate(raw_lines, start=1):
            if ki < len(kept) and (ln or "") == (kept[ki] or ""):
                keep(i, ln, [])
                ki += 1

        prov = {"raw_line_indices": raw_to_filtered_idx, "line_suppressions": line_suppressions}
        return filtered, prov

    if tag == "technical":
        kept = _apply_technical(raw_lines, primary, parsing_state)

        # Fail-open: if everything got stripped but we can see a content-looking paragraph, restore it.
        non_empty_original = any((ln or "").strip() for ln in raw_lines)
        non_empty_kept     = any((ln or "").strip() for ln in kept)
        if non_empty_original and not non_empty_kept:
            first_para = _first_content_paragraph(raw_lines)
            if first_para:
                kept = [first_para]  # restore just the strong first paragraph; rest remain suppressed

        # Rebuild provenance against raw_lines
        # Strategy: line-by-line positional comparison (helpers never reorder, only drop).
        ki = 0
        for i, ln in enumerate(raw_lines, start=1):
            if ki < len(kept) and (ln or "") == (kept[ki] or ""):
                keep(i, ln, [])
                ki += 1

        prov = {"raw_line_indices": raw_to_filtered_idx, "line_suppressions": line_suppressions}
        return filtered, prov

    # --- Default: keep lines as-is (preserve blanks), no suppressions
    for i, raw in enumerate(raw_lines, start=1):
        keep(i, (raw or ""), [])
    prov = {"raw_line_indices": raw_to_filtered_idx, "line_suppressions": line_suppressions}
    return filtered, prov
