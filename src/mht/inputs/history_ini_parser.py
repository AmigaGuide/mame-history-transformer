"""
History INI → classifications (stage orchestrator)

Parses Gaming-History INI files and emits:
- data/releases/<ver>/summaries/ini_parsing_summary.json     (diagnostic summary)
- data/releases/<ver>/outputs/gh_ini_classifications.json    (machine-centric map)

Design
------
This module is an orchestrator:
- Stamps/IO here only (skip-unchanged via utils.stamps.stage_is_fresh).
- Pure work is delegated to helpers:
  * utils.ini: INI parsing/normalisation and header metadata extraction
  * inputs.ini_summary: builds the summary document from parsed bundle
  * utils.selection: INI-based machine classification
  * utils.records: builds the machine-centric output map

Inputs
------
- Three GH INIs:
    - [GAMING HISTORY] Game Or No Game.ini
    - [GAMING HISTORY] Machine Category.ini
    - [GAMING HISTORY] Machine Type.ini

Notes
-----
- Behaviour: no filtering/selection policy here; we only surface what the INIs say.
- Writes the stamp only after both outputs are written successfully.
"""

from __future__ import annotations

from pathlib import Path
from collections import defaultdict
from typing import Dict
import time
import datetime

from mht.utils.config import LOG_LEVEL
from mht.utils.logger import setup_logger, debug_log
from mht.utils.stamps import save_stamp, stage_is_fresh
from mht.utils.paths import (
    ini_game_path, ini_category_path, ini_type_path,   # INI inputs
    ini_summary_path, ini_classifications_path,        # outputs
    ENCODINGS_JSON, stamps_dir,                        # stamp input + per-release stamps
)
from mht.utils.io import write_json
from mht.utils.ini import (
    ini_version_info,
    parse_ini_file_extended,
)
from mht.inputs.ini_summary import build_ini_summary
from mht.utils.records import build_ini_class_map
from mht.utils.validator import validate_ini_parsed_bundle


log = setup_logger(log_level=LOG_LEVEL)

__all__ = [
    "parse_history_inis",
    "load_ini_classifications",
]

def _ini_input_paths() -> dict[str, Path]:
    """Resolve the three INI input paths for the ACTIVE release at call time."""
    return {
        "game_status": ini_game_path(),
        "category":    ini_category_path(),
        "type":        ini_type_path(),
    }

# Output normalisation
GAME_STATUS_MAP = {"Game": "game", "No Game": "no_game"}
UNKNOWN = "unknown"


# --------------------------------------------------------------------------------------
# Public pure workers
# --------------------------------------------------------------------------------------

def load_ini_classifications(encodings: Dict[str, str]) -> Dict[str, dict]:
    """
    Parse the three GH INIs into an extended, analysis-friendly bundle (pure).

    Parameters
    ----------
    encodings : dict
        Map of filename -> text encoding, typically read from a per-release manifest.

    Returns
    -------
    dict
        {
          "game_status": {
            "machine_sections": {name -> set(section)},
            "section_listed_counts": {section -> listed_count},
            "section_unique_sets": {section -> set(unique_names)},
            "entries_listed": int,
            "machines_with_multiple_sections": int,
            "duplicates_across_sections": int,
            "duplicates_within_section": int,
            "version": {mame_version?, mame_build?, generated_date?},
            "encoding": "<encoding>"
          },
          "category": { ... },
          "type":     { ... }
        }

    Notes
    -----
    - Missing INIs yield empty structures with an informative warning.
    - Version metadata is scraped from the INI header region (first ~16 KiB).
    """
    t0 = time.perf_counter()
    parsed: Dict[str, dict] = {}

    for key, path in _ini_input_paths().items():
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
        ext["encoding"] = enc
        parsed[key] = ext

    log.info(f"INI classification data loaded in {time.perf_counter() - t0:.2f} seconds")
    return parsed

# --------------------------------------------------------------------------------------
# Orchestrator (I/O + stamps)
# --------------------------------------------------------------------------------------

def parse_history_inis(data_dir: Path, encodings: Dict[str, str]) -> bool:
    """
    Orchestrate the History INI stage: stamp check → parse → summarise → write.

    Parameters
    ----------
    data_dir : Path
        Base directory for data files (unused directly here; paths come from utils.paths).
    encodings : dict
        Map of filename -> encoding for the three INIs.

    Returns
    -------
    bool
        True on success (or when the stage is fresh and skipped). False on write failure
        or IO errors (stamp is not saved in that case).

    Side effects
    ------------
    - Writes:
        * data/releases/<ver>/summaries/ini_parsing_summary.json
        * data/releases/<ver>/outputs/gh_ini_classifications.json
    - Maintains a stage stamp at data/releases/<ver>/.stamps/ini.json (created only on success).
    """
    t0 = time.perf_counter()
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"

    # --- Stage stamp: skip unchanged (per-release) ---
    ini_paths = list(_ini_input_paths().values())
    #fresh, stamp_path, current_stamp = stage_is_fresh(
    #    "ini.json",
    #    stamps_dir=stamps_dir(),
    #    schema_id="mht.stage.ini",
    #    tool="ini_summary",
    #    inputs=ini_paths,
    #)    
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
    # Warnings-only invariants over the parsed bundle
    ini_issues = validate_ini_parsed_bundle(parsed, log)
    if ini_issues == 0:
        debug_log("[history_metadata] INI invariants passed")

    # 2) Build summary (pure)
    summary = build_ini_summary(parsed, now_iso)

    # 3) Build machine-centric map (pure)
    class_map = build_ini_class_map(parsed)

    # 4) Write outputs (I/O only here)
    ok_summary = write_json(ini_summary_path(), summary, sort_keys=False)
    ok_output  = write_json(ini_classifications_path(),   class_map, sort_keys=True)

    # 5) Only persist the stamp if both writes were successful
    if ok_summary and ok_output:
        save_stamp(stamp_path, current_stamp)
        duration = time.perf_counter() - t0
        log.info(f"INI parsing completed in {duration:.2f}s; ok_summary={ok_summary}, ok_output={ok_output}")
        return True

    log.error("Failed to write one or more INI outputs; not saving stamp.")
    return False
