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
        # Preserve paragraph separators
        if not (ln or "").strip():
            out.append("")       # keep blank line to delimit paragraphs
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
    out: List[str] = []
    for ln in lines:
        # Preserve paragraph separators
        if not (ln or "").strip():
            out.append("")       # keep blank line to delimit paragraphs
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

        # Narrative/spec heuristics
        if _HW_PROCESSOR_RE.search(ln):
            _record(parsing_state, system, "technical", "technical_processor_line", ln);           continue
        if _HW_CHIPSET_RE.search(ln):
            _record(parsing_state, system, "technical", "technical_chipset_line", ln);             continue
        if _HW_FREQUENCY_RE.search(ln):
            _record(parsing_state, system, "technical", "technical_frequency_line", ln);           continue
        if _HW_MEMORY_RE.search(ln):
            _record(parsing_state, system, "technical", "technical_memory_line", ln);              continue

        if _N_WAY_JOYSTICK_RE.search(ln):
            _record(parsing_state, system, "technical", "technical_joystick_n_way_line", ln);      continue

        out.append(ln)
    return out

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
            "line_suppressions": Dict[int, List[str]]  # filtered idx -> suppression keys applied on that line
        }
    """
    filtered: List[str] = []
    raw_to_filtered_idx: List[int] = []   # 1-based raw line numbers per kept line
    line_suppressions: Dict[int, List[str]] = {}

    # internal helper to register a kept line
    def keep(raw_idx: int, text: str, suppress_keys: List[str]) -> None:
        filtered.append(text)
        raw_to_filtered_idx.append(raw_idx)
        if suppress_keys:
            line_suppressions[len(filtered) - 1] = list(suppress_keys)

    # --- walk raw lines; use your existing suppression logic per section
    # we assume you increment global counters in parsing_state["suppressions"]["counts"]
    # and optionally record parsing_state["fully_suppressed_sections"][tag] elsewhere.
    counters = parsing_state.setdefault("suppressions", {}).setdefault("counts", {})

    tag = (section_tag or "").strip().lower()
    for i, raw in enumerate(raw_lines, start=1):
        line = (raw or "")
        suppress_keys: List[str] = []

        # ---- Overview suppressions (examples; reuse your existing tests) ----
        if tag == "overview":
            # type line
            if line.strip().lower().startswith("arcade video game"):
                counters["overview_type_line"] = counters.get("overview_type_line", 0) + 1
                suppress_keys.append("overview_type_line")
                # skip: do not keep this line
                continue
            # title/year/publisher line e.g. 'Puckman (c) 1980 Namco.'
            if ("(c)" in line) or ("©" in line):
                counters["overview_title_line"] = counters.get("overview_title_line", 0) + 1
                suppress_keys.append("overview_title_line")
                continue

        # ---- Technical suppressions (examples; reuse your existing tests) ----
        if tag == "technical":
            lower = line.lower()
            # players
            if lower.startswith("players"):
                counters["technical_players_line"] = counters.get("technical_players_line", 0) + 1
                suppress_keys.append("technical_players_line")
                continue
            # control / joystick / n-way
            if any(k in lower for k in ("control", "joystick")):
                # buttons handled separately below
                counters["technical_control_line"] = counters.get("technical_control_line", 0) + 1
                suppress_keys.append("technical_control_line")
                # if this is *only* controls metadata, skip the line
                continue
            # buttons (also catch pair-ish like 'Buttons per player - 1 (FIRE)')
            if "button" in lower or "buttons" in lower:
                counters["technical_buttons_line"] = counters.get("technical_buttons_line", 0) + 1
                suppress_keys.append("technical_buttons_line")
                continue
            # CPU / sound
            if "cpu" in lower:
                if "sound" in lower:
                    counters["technical_sound_cpu_line"] = counters.get("technical_sound_cpu_line", 0) + 1
                    suppress_keys.append("technical_sound_cpu_line")
                else:
                    counters["technical_cpu_line"] = counters.get("technical_cpu_line", 0) + 1
                    suppress_keys.append("technical_cpu_line")
                continue
            if "sound chip" in lower or "sound chips" in lower:
                counters["technical_sound_chips_line"] = counters.get("technical_sound_chips_line", 0) + 1
                suppress_keys.append("technical_sound_chips_line")
                continue
            # screen & video characteristics
            if "screen orientation" in lower:
                counters["technical_screen_orientation_line"] = counters.get("technical_screen_orientation_line", 0) + 1
                suppress_keys.append("technical_screen_orientation_line")
                continue
            if "screen resolution" in lower or "video resolution" in lower or "display resolution" in lower:
                counters["technical_screen_resolution_line"] = counters.get("technical_screen_resolution_line", 0) + 1
                suppress_keys.append("technical_screen_resolution_line")
                continue
            if "refresh rate" in lower or "screen refresh" in lower:
                counters["technical_refresh_rate_line"] = counters.get("technical_refresh_rate_line", 0) + 1
                suppress_keys.append("technical_refresh_rate_line")
                continue
            if "palette colour" in lower or "palette color" in lower or "on-screen color" in lower or "on-screen colour" in lower:
                counters["technical_palette_colours_line"] = counters.get("technical_palette_colours_line", 0) + 1
                suppress_keys.append("technical_palette_colours_line")
                continue
            # processor/chipset/frequency/memory families
            if any(k in lower for k in ("processor", "chipset")):
                counters["technical_processor_line"] = counters.get("technical_processor_line", 0) + 1
                suppress_keys.append("technical_processor_line")
                continue
            if "mhz" in lower or "khz" in lower or "ghz" in lower:
                counters["technical_frequency_line"] = counters.get("technical_frequency_line", 0) + 1
                suppress_keys.append("technical_frequency_line")
                continue
            if any(k in lower for k in ("memory", "sram", "dram", "vram")):
                counters["technical_memory_line"] = counters.get("technical_memory_line", 0) + 1
                suppress_keys.append("technical_memory_line")
                continue
            # specific phrases you logged earlier
            if "=> [" in line:
                counters["technical_control_mapping_line"] = counters.get("technical_control_mapping_line", 0) + 1
                suppress_keys.append("technical_control_mapping_line")
                continue
            if "buttons per player" in lower:
                counters["technical_buttons_pair_line"] = counters.get("technical_buttons_pair_line", 0) + 1
                suppress_keys.append("technical_buttons_pair_line")
                continue
            if "game size" in lower:
                counters["technical_game_size_line"] = counters.get("technical_game_size_line", 0) + 1
                suppress_keys.append("technical_game_size_line")
                continue
            if "control per player" in lower:
                counters["technical_control_per_player_line"] = counters.get("technical_control_per_player_line", 0) + 1
                suppress_keys.append("technical_control_per_player_line")
                continue
            if " joystick" in lower and "-way" in lower:
                counters["technical_joystick_n_way_line"] = counters.get("technical_joystick_n_way_line", 0) + 1
                suppress_keys.append("technical_joystick_n_way_line")
                continue
            if line.lower().startswith("display"):
                counters["technical_display_line"] = counters.get("technical_display_line", 0) + 1
                suppress_keys.append("technical_display_line")
                continue

        # keep the line (no suppressions fired)
        keep(i, line, suppress_keys)

    prov = {
        "raw_line_indices": raw_to_filtered_idx,       # aligns with filtered list
        "line_suppressions": line_suppressions         # filtered_idx -> [keys]
    }
    return filtered, prov
