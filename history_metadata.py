"""
Filename: history_metadata.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Parses classification metadata from three Gaming-History .ini files:
- Game Or No Game.ini
- Machine Category.ini
- Machine Type.ini

Outputs:
1) data/ini_parsing_summary.json          (diagnostic summary for audit)
2) output/gh_ini_classifications.json     (machine-centric parsed map)

Returns True/False from the entry point to indicate parse success.

Notes:
- Summary reports section labels exactly as found (e.g. "<not available>").
- Parsed JSON converts "<not available>" to "unknown" and defaults missing fields to "unknown".
- Category in output is always an array (even if a single label).
- This module does not compute file size/hash/mtime and does not touch the manifest.
"""

from pathlib import Path
from collections import defaultdict
from typing import Dict, Tuple, List, Set
import json
import time
import datetime
import re

from config import LOG_LEVEL
from logger import setup_logger, debug_log

log = setup_logger(log_level=LOG_LEVEL)

# Default locations
DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")

INI_FILES = {
    "game_status": DATA_DIR / "[GAMING HISTORY] Game Or No Game.ini",
    "category":    DATA_DIR / "[GAMING HISTORY] Machine Category.ini",
    "type":        DATA_DIR / "[GAMING HISTORY] Machine Type.ini",
}

# Internal cache of parsed structures (per INI key)
_parsed: Dict[str, dict] = {}
_ini_parsed = False

# Output normalisation
GAME_STATUS_MAP = {"Game": "game", "No Game": "no_game"}
UNKNOWN = "unknown"
VALID_ARCADE_CATEGORIES = {"Arcade", "Coin-Op (Games)"}  # helper only


# ----------------------------
# Helpers
# ----------------------------

def _to_iso_date(s: str) -> str | None:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            pass
    return None


def _ini_version_info(p: Path, encoding: str = "utf-8") -> dict:
    """Extract version/build and generated date from the INI header region."""
    try:
        with open(p, "r", encoding=encoding, errors="replace") as f:
            head = f.read(16384)  # first 16 KB is plenty
    except Exception:
        return {}

    head = head.lstrip("\ufeff")
    head = re.sub(r"\s+", " ", head)

    info: dict[str, str] = {}

    mv = re.search(r"(?i)\bMAME\s+([0-9.]+)\b", head)
    mb = re.search(r"(?i)\((mame[0-9]+)\)", head)
    if mv:
        info["mame_version"] = mv.group(1)
    if mb:
        info["mame_build"] = mb.group(1).lower()

    dt = re.search(
        r"(?i)(?:generated|updated)\s*(?:@|on|:)?\s*([0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})",
        head,
    )
    if dt:
        raw = dt.group(1)
        info["generated_date_raw"] = raw
        iso = _to_iso_date(raw)
        if iso:
            info["generated_date"] = iso

    return info


def _normalise_section_header(label: str) -> str:
    """Trim edges and collapse internal whitespace; preserve case and punctuation."""
    label = label.strip()
    label = re.sub(r"\s+", " ", label)
    return label


def _is_not_available_label(label: str | None) -> bool:
    if not label:
        return False
    return re.fullmatch(r"\s*<\s*not\s+available\s*>\s*", label, flags=re.IGNORECASE) is not None


def _ini_line_counts(p: Path, encoding: str = "utf-8") -> Tuple[int, int]:
    """Return (lines, non_comment_lines). ';;' denotes comments; blank lines ignored."""
    lines = non_comment = 0
    with open(p, encoding=encoding) as f:
        for line in f:
            lines += 1
            s = line.strip()
            if s and not s.startswith(";;"):
                non_comment += 1
    return lines, non_comment


def _parse_ini_file_extended(path: Path, encoding: str) -> dict:
    """
    Parse GH-style INIs where each [section] is followed by machine names.

    Returns a dict with:
      - machine_sections: Dict[str, Set[str]]  # machine -> set of sections (normalised)
      - section_listed_counts: Dict[str, int]  # per section, count of listed entries
      - section_unique_sets: Dict[str, Set[str]]  # per section, unique machine names
      - entries_listed: int
      - duplicates_across_sections: int  # total extra assignments beyond first
      - machines_with_multiple_sections: int
      - duplicates_within_section: int   # repeated same machine within same section (rare)
    """
    current_section = None
    machine_sections: Dict[str, Set[str]] = defaultdict(set)
    section_listed_counts: Dict[str, int] = defaultdict(int)
    section_unique_sets: Dict[str, Set[str]] = defaultdict(set)

    with open(path, encoding=encoding) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith(";;"):
                continue
            if line.startswith("[") and line.endswith("]"):
                sec = _normalise_section_header(line[1:-1])
                current_section = sec
                continue
            if current_section and current_section != "FOLDER_SETTINGS":
                name = line
                section_listed_counts[current_section] += 1
                if name in section_unique_sets[current_section]:
                    # duplicate within same section
                    pass
                section_unique_sets[current_section].add(name)
                machine_sections[name].add(current_section)

    entries_listed = sum(section_listed_counts.values())
    machines_with_multiple_sections = sum(1 for s in machine_sections.values() if len(s) >= 2)
    # Extra assignments beyond first per machine
    duplicates_across_sections = sum(len(s) - 1 for s in machine_sections.values() if len(s) >= 1)
    # Within-section duplicates = listed - sum of unique per section
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


def _load_ini_classifications(encodings: Dict[str, str]) -> Dict[str, dict]:
    """Load all classification INIs into the internal cache."""
    global _ini_parsed
    if _ini_parsed:
        return _parsed

    t0 = time.perf_counter()
    for key, path in INI_FILES.items():
        enc = encodings.get(path.name, "utf-8")
        debug_log(f"[history_metadata] Parsing {path.name} with encoding {enc}...")
        if not path.exists():
            log.warning(f"Missing INI: {path.name}")
            _parsed[key] = {
                "machine_sections": defaultdict(set),
                "section_listed_counts": defaultdict(int),
                "section_unique_sets": defaultdict(set),
                "entries_listed": 0,
                "machines_with_multiple_sections": 0,
                "duplicates_across_sections": 0,
                "duplicates_within_section": 0,
                "version": {},
                "encoding": enc,
            }
            continue

        ext = _parse_ini_file_extended(path, enc)
        ext["version"] = _ini_version_info(path, encoding=enc)
        ext["encoding"] = enc
        _parsed[key] = ext

    _ini_parsed = True
    log.info(f"INI classification data loaded in {time.perf_counter() - t0:.2f} seconds")
    return _parsed


# ----------------------------
# Public lookups
# ----------------------------

def classify_machine(machine_name: str, encodings: Dict[str, str]) -> Dict[str, object]:
    """
    Return classification details for a MAME machine from the .ini metadata.
    Fields:
      - game_status: 'game' | 'no_game' | 'unknown'
      - category:    List[str]  (always an array; ['unknown'] if missing)
      - type:        str        ('unknown' if missing)
    """
    _load_ini_classifications(encodings)

    # Game status
    gs_set = _parsed["game_status"]["machine_sections"].get(machine_name, set())
    if _is_not_available_label(next(iter(gs_set), None)) and len(gs_set) == 1:
        game_status = UNKNOWN
    elif "Game" in gs_set:
        game_status = "game"
    elif "No Game" in gs_set:
        game_status = "no_game"
    elif gs_set:
        # Unexpected label in Game Or No Game.ini; treat as unknown
        game_status = UNKNOWN
    else:
        game_status = UNKNOWN

    # Category (array)
    cat_set = _parsed["category"]["machine_sections"].get(machine_name, set()).copy()
    # Map '<not available>' to 'unknown' in output, but keep others verbatim
    cat_labels = []
    for c in cat_set:
        if _is_not_available_label(c):
            cat_labels.append(UNKNOWN)
        else:
            cat_labels.append(c)
    if not cat_labels:
        cat_labels = [UNKNOWN]
    # Remove 'unknown' if concrete categories exist
    if len(cat_labels) > 1 and UNKNOWN in cat_labels:
        cat_labels = [c for c in cat_labels if c != UNKNOWN]
    category_list = sorted(set(cat_labels))

    # Type (single)
    type_set = _parsed["type"]["machine_sections"].get(machine_name, set())
    if not type_set:
        machine_type = UNKNOWN
    elif any(_is_not_available_label(t) for t in type_set):
        machine_type = UNKNOWN
    else:
        machine_type = sorted(type_set)[0]  # deterministic pick if ever multiple

    return {"game_status": game_status, "category": category_list, "type": machine_type}


def is_valid_arcade_game(machine_name: str, encodings: Dict[str, str]) -> bool:
    """True if machine is 'game' AND category includes Arcade or Coin-Op (Games)."""
    info = classify_machine(machine_name, encodings)
    return (info["game_status"] == "game") and any(c in VALID_ARCADE_CATEGORIES for c in info["category"])


# ----------------------------
# Summary helpers
# ----------------------------

def _sorted_counts_from_listed(d: Dict[str, int]) -> Dict[str, int]:
    return {k: d[k] for k in sorted(d.keys())}


def _sorted_counts_from_unique_sets(d: Dict[str, Set[str]]) -> Dict[str, int]:
    return {k: len(d[k]) for k in sorted(d.keys())}


# ----------------------------
# Writers
# ----------------------------

def _write_ini_summary(data_dir: Path, encodings: Dict[str, str]) -> Tuple[bool, str]:
    """
    Build and write data/ini_parsing_summary.json

    Per INI we include:
      - filename, encoding, version
      - entries_listed (all lines under sections)
      - entries_indexed (unique machines)
      - sections_total
      - section_counts_listed
      - section_counts_unique
      - machines_with_multiple_sections
      - duplicate_assignments
    """
    now = datetime.datetime.utcnow().isoformat() + "Z"
    files_block = {}
    errors: List[str] = []

    # Union over all INIs (for lean coverage figures)
    union_names: Set[str] = set()

    for key, path in INI_FILES.items():
        enc = _parsed.get(key, {}).get("encoding", encodings.get(path.name, "utf-8"))
        version = _parsed.get(key, {}).get("version", {})

        ms: Dict[str, Set[str]] = _parsed.get(key, {}).get("machine_sections", {})
        slc: Dict[str, int]      = _parsed.get(key, {}).get("section_listed_counts", {})
        sus: Dict[str, Set[str]] = _parsed.get(key, {}).get("section_unique_sets", {})

        union_names |= set(ms.keys())

        entries_listed = _parsed.get(key, {}).get("entries_listed", 0)
        entries_indexed = len(ms)
        sections_total = len(slc.keys() | sus.keys())

        files_block[key] = {
            "filename": path.name,
            "encoding": enc,
            "version": version if version else {},
            "entries_listed": entries_listed,
            "entries_indexed": entries_indexed,
            "sections_total": sections_total,
            "section_counts_listed": _sorted_counts_from_listed(slc),
            "section_counts_unique": _sorted_counts_from_unique_sets(sus),
            "machines_with_multiple_sections": _parsed.get(key, {}).get("machines_with_multiple_sections", 0),
            "duplicate_assignments": _parsed.get(key, {}).get("duplicates_across_sections", 0),
        }

        if not path.exists():
            errors.append(f"Missing INI: {path.name}")

    coverage = {
        "unique_machine_names_union": len(union_names),
        "with_game_status": len(_parsed.get("game_status", {}).get("machine_sections", {})),
        "missing_in_game_status": len(union_names) - len(_parsed.get("game_status", {}).get("machine_sections", {})),
        "with_category": len(_parsed.get("category", {}).get("machine_sections", {})),
        "missing_in_category": len(union_names) - len(_parsed.get("category", {}).get("machine_sections", {})),
        "with_type": len(_parsed.get("type", {}).get("machine_sections", {})),
        "missing_in_type": len(union_names) - len(_parsed.get("type", {}).get("machine_sections", {})),
    }

    summary = {
        "ini": {
            "ini_parser_schema": "1.1",
            "generated_at": now,
            "files": files_block,
        },
        "totals": coverage,
        "errors": errors,
    }

    out_path = data_dir / "ini_parsing_summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        log.info(f"Wrote {out_path}")
        return True, str(out_path).replace("\\", "/")
    except Exception as e:
        log.error(f"Failed to write INI summary: {e}")
        return False, str(out_path).replace("\\", "/")


def _write_machine_centric_output(output_dir: Path, encodings: Dict[str, str]) -> Tuple[bool, str]:
    """
    Build and write output/gh_ini_classifications.json

    - Union of machine names across the three INIs
    - game_status: string (game | no_game | unknown)
    - category:    array of strings (always array; ['unknown'] if none)
    - type:        string (unknown if '<not available>' or missing)
    """
    # Union of names across the three mappings
    union_names: Set[str] = set()
    for key in ("game_status", "category", "type"):
        union_names |= set(_parsed.get(key, {}).get("machine_sections", {}).keys())

    names_sorted = sorted(union_names)

    out_map: Dict[str, dict] = {}
    for name in names_sorted:
        # Reuse classify_machine for consistent rules
        info = classify_machine(name, encodings)
        out_map[name] = info

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "gh_ini_classifications.json"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out_map, f, indent=2, ensure_ascii=False)
        log.info(f"Wrote {out_path}")
        return True, str(out_path).replace("\\", "/")
    except Exception as e:
        log.error(f"Failed to write INI classifications: {e}")
        return False, str(out_path).replace("\\", "/")


# ----------------------------
# Entry point for main.py
# ----------------------------

def parse_history_inis(data_dir: Path, encodings: Dict[str, str]) -> bool:
    """
    Entry point expected by main.py.

    Behaviour:
    - Load and cache the three INIs.
    - Write data/ini_parsing_summary.json (per-file counts; coverage; duplicates).
    - Write output/gh_ini_classifications.json (machine-centric; category as array).
    - Return True on success; False otherwise.
    """
    t0 = time.perf_counter()
    _load_ini_classifications(encodings)

    ok_summary, _ = _write_ini_summary(data_dir, encodings)
    ok_output, _  = _write_machine_centric_output(OUTPUT_DIR, encodings)

    duration = time.perf_counter() - t0
    log.info(f"INI parsing completed in {duration:.2f}s; ok_summary={ok_summary}, ok_output={ok_output}")

    return bool(ok_summary and ok_output)
