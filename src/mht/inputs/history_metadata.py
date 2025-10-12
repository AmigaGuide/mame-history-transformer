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
from mht.utils.stamps import save_stamp, stage_is_fresh
from mht.utils.paths import (
    DATA_DIR, OUTPUT_DIR, STAMPS_DIR,
    INI_GAME, INI_CATEGORY, INI_TYPE,
    INI_SUMMARY, INI_CLASS_PATH,
    ENCODINGS_JSON,
)
from mht.utils.headers import build_summary_header
from mht.utils.io import write_json
from mht.utils.ini import (
    ini_version_info,
    parse_ini_file_extended,
    is_not_available_label,
    sorted_counts_from_listed,
    sorted_counts_from_unique_sets,
)
from mht.inputs.ini_summary import build_ini_summary
from mht.utils.selection import classify_from_ini


log = setup_logger(log_level=LOG_LEVEL)

__all__ = [
    "parse_history_inis",
    "load_ini_classifications",
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

        ext = parse_ini_file_extended(path, enc)
        ext["version"] = ini_version_info(path, encoding=enc)
        #ext = _parse_ini_file_extended(path, enc)
        #ext["version"] = _ini_version_info(path, encoding=enc)
        ext["encoding"] = enc
        parsed[key] = ext

    log.info(f"INI classification data loaded in {time.perf_counter() - t0:.2f} seconds")
    return parsed

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
    #for name in names_sorted:
    #    out_map[name] = classify_machine(name, parsed)
    for name in names_sorted:
        out_map[name] = classify_from_ini(name, parsed)
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
    ini_paths = list(INI_FILES.values())

    fresh, stamp_path, current_stamp = stage_is_fresh(
        "ini.json",
        schema_id="mht.stage.ini",
        tool="ini_summary",
        inputs=[*ini_paths, ENCODINGS_JSON],
    )
    if fresh:
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
