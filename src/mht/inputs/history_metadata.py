# Filename: history_metadata.py
# Author: XtC
#
# Purpose:
# Parse classification metadata from three Gaming-History INI files:
# - [GAMING HISTORY] Game Or No Game.ini
# - [GAMING HISTORY] Machine Category.ini
# - [GAMING HISTORY] Machine Type.ini
#
# Pure workers (no I/O, no stamps):
#   - load_ini_classifications(encodings) -> parsed bundle
#   - build_ini_summary(parsed, now_iso)  -> summary dict for data/ini_parsing_summary.json
#   - build_machine_classifications(parsed) -> map for output/gh_ini_classifications.json
#
# Orchestrator (I/O + stamps only):
#   - parse_history_inis(data_dir, encodings) -> bool
#
# Outputs (unchanged):
#   1) data/ini_parsing_summary.json       (diagnostic summary for audit)
#   2) output/gh_ini_classifications.json  (machine-centric parsed map)
#

from __future__ import annotations

from pathlib import Path
from collections import defaultdict
from typing import Dict, Tuple, List, Set
import json
import time
import datetime
import re

from mht.utils.config import LOG_LEVEL
from mht.utils.logger import setup_logger, debug_log
from mht.utils.versions import SCHEMA_IDS, schema_version, tool_version
from mht.utils.stamps import make_stamp, load_stamp, save_stamp, is_fresh
from mht.utils.paths import (
    DATA_DIR, OUTPUT_DIR, STAMPS_DIR,
    INI_GAME, INI_CATEGORY, INI_TYPE,
    INI_SUMMARY, INI_CLASS_PATH,
    ENCODINGS_JSON,
)
from mht.utils.headers import build_summary_header
from mht.utils.io import write_json

log = setup_logger(log_level=LOG_LEVEL)

__all__ = [
    "parse_history_inis",
    "classify_machine",
    "load_ini_classifications",
    "build_ini_summary",
    "build_machine_classifications",
    "INI_FILES",
]

# INI input locations (centralised)
INI_FILES = {
    "game_status": INI_GAME,
    "category":    INI_CATEGORY,
    "type":        INI_TYPE,
}

# Output normalisation
GAME_STATUS_MAP = {"Game": "game", "No Game": "no_game"}
UNKNOWN = "unknown"

# --------------------------------------------------------------------------------------
# Helpers (pure)
# --------------------------------------------------------------------------------------

def _to_iso_date(s: str) -> str | None:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            pass
    return None

def _ini_version_info(p: Path, encoding: str) -> dict:
    """Extract version/build and generated date from the INI header region."""
    try:
        with open(p, "r", encoding=encoding, errors="replace") as f:
            head = f.read(16384)
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
    dt = re.search(r"(?i)(?:generated|updated)\s*(?:@|on|:)?\s*([0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})", head)
    if dt:
        raw = dt.group(1)
        info["generated_date_raw"] = raw
        iso = _to_iso_date(raw)
        if iso:
            info["generated_date"] = iso
    return info

def _normalise_section_header(label: str) -> str:
    label = label.strip()
    label = re.sub(r"\s+", " ", label)
    return label

def _is_not_available_label(label: str | None) -> bool:
    if not label:
        return False
    return re.fullmatch(r"\s*<\s*not\s+available\s*>\s*", label, flags=re.IGNORECASE) is not None

def _parse_ini_file_extended(path: Path, encoding: str) -> dict:
    """Return extended structure: machine_sections + per-section counts/uniques & duplicate stats."""
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
                section_unique_sets[current_section].add(name)
                machine_sections[name].add(current_section)

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

def _sorted_counts_from_listed(d: Dict[str, int]) -> Dict[str, int]:
    return {k: d[k] for k in sorted(d.keys())}

def _sorted_counts_from_unique_sets(d: Dict[str, Set[str]]) -> Dict[str, int]:
    return {k: len(d[k]) for k in sorted(d.keys())}

# --------------------------------------------------------------------------------------
# Public pure workers
# --------------------------------------------------------------------------------------

def load_ini_classifications(encodings: Dict[str, str]) -> Dict[str, dict]:
    """
    Load and parse all three INIs. No file writes, no stamps.
    Returns a dict keyed by {"game_status","category","type"} with extended stats.
    """
    t0 = time.perf_counter()
    parsed: Dict[str, dict] = {}

    for key, path in INI_FILES.items():
        enc = encodings.get(path.name, "utf-8")
        debug_log(f"[history_metadata] Parsing {path.name} with encoding {enc}...")
        if not path.exists():
            log.warning(f"Missing INI: {path.name}")
            parsed[key] = {
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
        parsed[key] = ext

    log.info(f"INI classification data loaded in {time.perf_counter() - t0:.2f} seconds")
    return parsed


def build_ini_summary(parsed: Dict[str, dict], now_iso: str) -> dict:
    """
    Build the summary object for data/ini_parsing_summary.json from a parsed bundle.
    """
    files_block: Dict[str, dict] = {}
    errors: List[str] = []

    # Union of machine names across all INIs
    union_names: Set[str] = set()
    for key, path in INI_FILES.items():
        info = parsed.get(key, {}) or {}
        ms: Dict[str, Set[str]] = info.get("machine_sections", {})
        slc: Dict[str, int]      = info.get("section_listed_counts", {})
        sus: Dict[str, Set[str]] = info.get("section_unique_sets", {})
        union_names |= set(ms.keys())

        files_block[key] = {
            "filename": path.name,
            "encoding": info.get("encoding", "utf-8"),
            "version": info.get("version", {}) or {},
            "entries_listed": info.get("entries_listed", 0),
            "entries_indexed": len(ms),
            "sections_total": len((slc or {}).keys() | (sus or {}).keys()),
            "section_counts_listed": _sorted_counts_from_listed(slc or {}),
            "section_counts_unique": _sorted_counts_from_unique_sets(sus or {}),
            "machines_with_multiple_sections": info.get("machines_with_multiple_sections", 0),
            "duplicate_assignments": info.get("duplicates_across_sections", 0),
        }

        # If the original file was missing when parsed was built
        try:
            if not INI_FILES[key].exists():
                errors.append(f"Missing INI: {path.name}")
        except Exception:
            # Very defensive; should not happen
            errors.append(f"Missing INI: {path.name}")

    coverage = {
        "unique_machine_names_union": len(union_names),
        "with_game_status": len((parsed.get("game_status", {}) or {}).get("machine_sections", {})),
        "missing_in_game_status": len(union_names) - len((parsed.get("game_status", {}) or {}).get("machine_sections", {})),
        "with_category": len((parsed.get("category", {}) or {}).get("machine_sections", {})),
        "missing_in_category": len(union_names) - len((parsed.get("category", {}) or {}).get("machine_sections", {})),
        "with_type": len((parsed.get("type", {}) or {}).get("machine_sections", {})),
        "missing_in_type": len(union_names) - len((parsed.get("type", {}) or {}).get("machine_sections", {})),
    }

    # Header versions (consensus if possible)
    header_versions: Dict[str, str] = {"ini_generated_at": now_iso}
    mame_versions = {
        (v or {}).get("mame_version")
        for v in (files_block[k]["version"] for k in files_block)
        if v and (v.get("mame_version"))
    }
    if len(mame_versions) == 1:
        header_versions["mame_xml_version"] = next(iter(mame_versions))
    mame_builds = {
        (v or {}).get("mame_build")
        for v in (files_block[k]["version"] for k in files_block)
        if v and (v.get("mame_build"))
    }
    if len(mame_builds) == 1:
        header_versions["mame_build"] = next(iter(mame_builds))

    header = build_summary_header(
       schema_id=SCHEMA_IDS["ini"],
       schema_version=schema_version(SCHEMA_IDS["ini"]),
       versions={**header_versions, "ini_summary_version": tool_version("ini_summary")},
       generated_at=now_iso,
    )

    summary = {
        "header": header,
        "ini": {
            # Historically this field existed; keep it if your schema relies on it.
            # If not needed, it can be removed without affecting the header contract.
            # "ini_parser_schema": <optional>,
            "generated_at": now_iso,
            "files": files_block,
        },
        "totals": coverage,
        "errors": errors,
    }
    return summary


def classify_machine(machine_name: str, parsed: Dict[str, dict]) -> Dict[str, object]:
    """Pure classification lookup using the parsed INI bundle."""
    gs_set = (parsed.get("game_status", {}) or {}).get("machine_sections", {}).get(machine_name, set())
    if _is_not_available_label(next(iter(gs_set), None)) and len(gs_set) == 1:
        game_status = UNKNOWN
    elif "Game" in gs_set:
        game_status = "game"
    elif "No Game" in gs_set:
        game_status = "no_game"
    elif gs_set:
        game_status = UNKNOWN
    else:
        game_status = UNKNOWN

    # Category (array)
    cat_set = (parsed.get("category", {}) or {}).get("machine_sections", {}).get(machine_name, set()).copy()
    cat_labels = []
    for c in cat_set:
        cat_labels.append(UNKNOWN if _is_not_available_label(c) else c)
    if not cat_labels:
        cat_labels = [UNKNOWN]
    if len(cat_labels) > 1 and UNKNOWN in cat_labels:
        cat_labels = [c for c in cat_labels if c != UNKNOWN]
    category_list = sorted(set(cat_labels))

    # Type (single)
    type_set = (parsed.get("type", {}) or {}).get("machine_sections", {}).get(machine_name, set())
    if not type_set:
        machine_type = UNKNOWN
    elif any(_is_not_available_label(t) for t in type_set):
        machine_type = UNKNOWN
    else:
        machine_type = sorted(type_set)[0]

    return {"game_status": game_status, "category": category_list, "type": machine_type}


def build_machine_classifications(parsed: Dict[str, dict]) -> Dict[str, dict]:
    """
    Build the machine-centric map for output/gh_ini_classifications.json
    from the parsed bundle. Pure (no I/O).
    """
    union_names: Set[str] = set()
    for key in ("game_status", "category", "type"):
        union_names |= set((parsed.get(key, {}) or {}).get("machine_sections", {}).keys())

    names_sorted = sorted(union_names)
    out_map: Dict[str, dict] = {}
    for name in names_sorted:
        out_map[name] = classify_machine(name, parsed)
    return out_map

# --------------------------------------------------------------------------------------
# Orchestrator (I/O + stamps)
# --------------------------------------------------------------------------------------

def parse_history_inis(data_dir: Path, encodings: Dict[str, str]) -> bool:
    """
    Entry point expected by main.py.
    Performs stamp check, delegates to pure workers, writes files, and saves stamp.
    """
    t0 = time.perf_counter()
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"

    # --- Stage stamp: skip unchanged ---
    STAMPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp_path = STAMPS_DIR / "ini.json"
    ini_paths = list(INI_FILES.values())
    current_stamp = make_stamp(
        schema_id="mht.stage.ini",
        tool_version=tool_version("ini_summary"),
        #inputs=ini_paths,
        inputs = [*ini_paths, ENCODINGS_JSON],
    )
    prev = load_stamp(stamp_path)
    if is_fresh(current_stamp, prev):
        log.info("INI stage up-to-date (stamp matched) — skipping rebuild")
        return True

    # 1) Parse INIs (pure)
    parsed = load_ini_classifications(encodings)

    # 2) Build summary (pure)
    summary = build_ini_summary(parsed, now_iso)

    # 3) Build machine-centric map (pure)
    class_map = build_machine_classifications(parsed)

    # 4) Write outputs (I/O only here)
    ok_summary = write_json(INI_SUMMARY, summary, sort_keys=True)
    ok_output  = write_json(INI_CLASS_PATH, class_map, sort_keys=True)

    # 5) Only persist the stamp if both writes were successful
    if ok_summary and ok_output:
        save_stamp(stamp_path, current_stamp)
        duration = time.perf_counter() - t0
        log.info(f"INI parsing completed in {duration:.2f}s; ok_summary={ok_summary}, ok_output={ok_output}")
        return True

    log.error("Failed to write one or more INI outputs; not saving stamp.")
    return False
