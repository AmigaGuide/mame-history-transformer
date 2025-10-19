"""
INI helpers: parsing, normalisation, and light metadata extraction.

Includes:
- to_iso_date(): parse a date string in a couple of common formats to ISO.
- ini_version_info(): read version/build/date hints from an INI header.
- normalise_section_header(): tidy a [Section Name] label.
- is_not_available_label(): detect '<not available>' markers.
- parse_ini_file_extended(): parse an INI into extended section/machine stats.
- sorted_counts_from_listed()/sorted_counts_from_unique_sets(): small counters.
"""

from __future__ import annotations

from pathlib import Path
from collections import defaultdict
from typing import Dict, Set, Union, IO
import datetime
import re


def to_iso_date(s: str) -> str | None:
    """Return YYYY-MM-DD if s matches DD/MM/YYYY or YYYY-MM-DD; else None."""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            pass
    return None

def ini_version_info(src: Union[Path, IO[str]], encoding: str = "utf-8") -> dict:
    """
    Extract version/build and generated date from the INI header region.
    Reads only the first ~16 KiB for speed.

    Supports either:
      - Path to a file (opened here), or
      - An already-open text stream (e.g., TextIOWrapper from a zip member).
    """
    head = ""
    close_after = False
    try:
        if isinstance(src, Path):
            f = open(src, "r", encoding=encoding, errors="replace")
            close_after = True
        else:
            # Assume it's a text IO stream positioned at the start
            f = src

        head = f.read(16384)  # read only the first ~16 KiB
    except Exception:
        if close_after:
            try:
                f.close()
            except Exception:
                pass
        return {}
    finally:
        if close_after:
            try:
                f.close()
            except Exception:
                pass

    head = head.lstrip("\ufeff")
    head = re.sub(r"\s+", " ", head)

    info: dict[str, str] = {}

    mv = re.search(r"(?i)\bMAME\s+([0-9.]+)\b", head)
    if mv:
        info["mame_version"] = mv.group(1)

    mb = re.search(r"(?i)\((mame[0-9]+)\)", head)
    if mb:
        info["mame_build"] = mb.group(1).lower()

    dt = re.search(
        r"(?i)(?:generated|updated)\s*(?:@|on|:)?\s*("
        r"[0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2}"
        r")",
        head,
    )
    if dt:
        raw = dt.group(1)
        info["generated_date_raw"] = raw
        iso = to_iso_date(raw)
        if iso:
            info["generated_date"] = iso

    return info


def normalise_section_header(label: str) -> str:
    """Trim + collapse internal whitespace for a section label."""
    label = label.strip()
    label = re.sub(r"\s+", " ", label)
    return label

def is_not_available_label(label: str | None) -> bool:
    """True when the label is a variant of '<not available>' (case/space tolerant)."""
    if not label:
        return False
    return re.fullmatch(r"\s*<\s*not\s+available\s*>\s*", label, flags=re.IGNORECASE) is not None

def parse_ini_file_extended(src: Union[Path, IO[str]], encoding: str = "utf-8") -> dict:
    """
    Parse an INI file into an extended structure:
      - machine_sections: {machine -> set(sections)}
      - section_listed_counts: {section -> listed lines}
      - section_unique_sets: {section -> unique machine names}
      - entries_listed, machines_with_multiple_sections,
        duplicates_across_sections, duplicates_within_section
    """
    current_section = None
    machine_sections: Dict[str, Set[str]] = defaultdict(set)
    section_listed_counts: Dict[str, int] = defaultdict(int)
    section_unique_sets: Dict[str, Set[str]] = defaultdict(set)

    close_after = False
    if isinstance(src, Path):
        f = open(src, "r", encoding=encoding, errors="replace")
        close_after = True
    else:
        # assume already-open text stream (e.g. TextIOWrapper around a zip member)
        f = src

    try:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith(";;"):
                continue
            if line.startswith("[") and line.endswith("]"):
                sec = normalise_section_header(line[1:-1])
                current_section = sec
                continue
            if current_section and current_section != "FOLDER_SETTINGS":
                name = line
                section_listed_counts[current_section] += 1
                section_unique_sets[current_section].add(name)
                machine_sections[name].add(current_section)
    finally:
        if close_after:
            f.close()

    entries_listed = sum(section_listed_counts.values())
    machines_with_multiple_sections = sum(1 for s in machine_sections.values() if len(s) >= 2)
    duplicates_across_sections = sum(len(s) - 1 for s in machine_sections.values() if len(s) >= 1)
    duplicates_within_section = entries_listed - sum(len(s) for s in section_unique_sets.values())

    return {
        "machine_sections": machine_sections,
        "section_listed_counts": section_listed_counts,
        "section_unique_sets": section_unique_sets,
        "entries_listed": entries_listed,
        "machines_with_multiple_sections": machines_with_multiple_sections,
        "duplicates_across_sections": duplicates_across_sections,
        "duplicates_within_section": duplicates_within_section,
    }

def sorted_counts_from_listed(d: Dict[str, int]) -> Dict[str, int]:
    """Return {section -> count} sorted by section name."""
    return {k: d[k] for k in sorted(d.keys())}

def sorted_counts_from_unique_sets(d: Dict[str, Set[str]]) -> Dict[str, int]:
    """Return {section -> unique_count} sorted by section name."""
    return {k: len(d[k]) for k in sorted(d.keys())}
