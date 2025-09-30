"""
Filename: history_metadata.py
Version: 1.0.2
Last modified: 2025-09-30

Purpose:
Parse classification metadata from three Gaming-History INI files:
- [GAMING HISTORY] Game Or No Game.ini
- [GAMING HISTORY] Machine Category.ini
- [GAMING HISTORY] Machine Type.ini

Outputs:
1) data/ini_parsing_summary.json       (diagnostic summary for audit)
2) output/gh_ini_classifications.json  (machine-centric parsed map)
"""

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
)

__all__ = ["parse_history_inis", "classify_machine", "INI_FILES"]

log = setup_logger(log_level=LOG_LEVEL)

# INI input locations (centralised)
INI_FILES = {
    "game_status": INI_GAME,
    "category":    INI_CATEGORY,
    "type":        INI_TYPE,
}

# Internal cache of parsed structures (per INI key)
_parsed: Dict[str, dict] = {}
_ini_parsed = False

# Output normalisation
GAME_STATUS_MAP = {"Game": "game", "No Game": "no_game"}
UNKNOWN = "unknown"

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

def _load_ini_classifications(encodings: Dict[str, str]) -> Dict[str, dict]:
    """Load all classification INIs into the internal cache (idempotent)."""
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
        game_status = UNKNOWN
    else:
        game_status = UNKNOWN

    # Category (array)
    cat_set = _parsed["category"]["machine_sections"].get(machine_name, set()).copy()
    cat_labels = []
    for c in cat_set:
        cat_labels.append(UNKNOWN if _is_not_available_label(c) else c)
    if not cat_labels:
        cat_labels = [UNKNOWN]
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
        machine_type = sorted(type_set)[0]

    return {"game_status": game_status, "category": category_list, "type": machine_type}

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
    """
    now = datetime.datetime.utcnow().isoformat() + "Z"
    files_block = {}
    errors: List[str] = []

    # --- Stage stamp: skip unchanged ---
    STAMPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp_path = STAMPS_DIR / "ini.json"
    ini_paths = list(INI_FILES.values())
    current_stamp = make_stamp(
        schema_id="mht.stage.ini",
        tool_version=tool_version("ini_summary"),
        inputs=ini_paths,
    )
    prev = load_stamp(stamp_path)
    if is_fresh(current_stamp, prev):
        out_path = INI_SUMMARY
        log.info("INI stage up-to-date (stamp matched) — skipping rebuild")
        return True, str(out_path).replace("\\", "/")

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

    # Header versions (consensus if possible)
    header_versions: Dict[str, str] = {"ini_generated_at": now}
    mame_versions = {v.get("mame_version") for v in (files_block[k]["version"] for k in files_block) if v and v.get("mame_version")}
    if len(mame_versions) == 1:
        header_versions["mame_xml_version"] = next(iter(mame_versions))
    mame_builds = {v.get("mame_build") for v in (files_block[k]["version"] for k in files_block) if v and v.get("mame_build")}
    if len(mame_builds) == 1:
        header_versions["mame_build"] = next(iter(mame_builds))

    summary = {
        "header": {
            "schema_id": SCHEMA_IDS["ini"],
            "schema_version": schema_version(SCHEMA_IDS["ini"]),
            "generated_at": now,
            "versions": {
                **header_versions,
                "ini_summary_version": tool_version("ini_summary"),
            },
        },
        "ini": {
            "ini_parser_schema": "1.1",
            "generated_at": now,
            "files": files_block,
        },
        "totals": coverage,
        "errors": errors,
    }

    out_path = INI_SUMMARY
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        log.info(f"Wrote {out_path}")

        # Write the stamp only after successful output
        save_stamp(stamp_path, current_stamp)

        return True, str(out_path).replace("\\", "/")
    except Exception as e:
        log.error(f"Failed to write INI summary: {e}")
        return False, str(out_path).replace("\\", "/")

def _write_machine_centric_output(output_dir: Path, encodings: Dict[str, str]) -> Tuple[bool, str]:
    """
    Build and write output/gh_ini_classifications.json
    """
    union_names: Set[str] = set()
    for key in ("game_status", "category", "type"):
        union_names |= set(_parsed.get(key, {}).get("machine_sections", {}).keys())

    names_sorted = sorted(union_names)
    out_map: Dict[str, dict] = {}
    for name in names_sorted:
        out_map[name] = classify_machine(name, encodings)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INI_CLASS_PATH
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
    """
    t0 = time.perf_counter()
    _load_ini_classifications(encodings)

    ok_summary, _ = _write_ini_summary(DATA_DIR, encodings)
    ok_output, _  = _write_machine_centric_output(OUTPUT_DIR, encodings)

    duration = time.perf_counter() - t0
    log.info(f"INI parsing completed in {duration:.2f}s; ok_summary={ok_summary}, ok_output={ok_output}")
    return bool(ok_summary and ok_output)
