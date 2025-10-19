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
import zipfile, tempfile, os
import shutil

from mht.utils.config import LOG_LEVEL
from mht.utils.logger import setup_logger, debug_log
from mht.utils.stamps import save_stamp, stage_is_fresh
from mht.utils.paths import (
    ini_game_path, ini_category_path, ini_type_path,   # INI inputs
    ini_summary_path, ini_classifications_path,        # outputs
    ENCODINGS_JSON, stamps_dir,                        # stamp input + per-release stamps
    archives_dir, active_version,
)
from mht.utils.io import write_json
from mht.utils.ini import (
    ini_version_info,
    parse_ini_file_extended,
)
from mht.inputs.ini_summary import build_ini_summary
from mht.utils.records import build_ini_class_map
from mht.utils.validator import validate_ini_parsed_bundle
from mht.provenance.peek import find_gh_ini_members


log = setup_logger(log_level=LOG_LEVEL)

# Output normalisation
GAME_STATUS_MAP = {"Game": "game", "No Game": "no_game"}
UNKNOWN = "unknown"

# Module-level (will be set per run inside parse_history_inis)
INI_FILES: dict[str, Path] = {}


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
            # Try to source from a GH zip in the current release's archives
            ver = active_version()
            gh_zip = None
            arc_dir = archives_dir(ver)
            if arc_dir.exists():
                # heuristic: prefer zips with 'history' in the name
                zips = sorted([p for p in arc_dir.iterdir() if p.suffix.lower() == ".zip"], key=lambda p: p.name.lower())
                gh_cands = [p for p in zips if "history" in p.name.lower()] or zips
                gh_zip = gh_cands[0] if gh_cands else None

            if not gh_zip:
                log.warning(f"Missing INI: {path.name} (no GH zip found in {arc_dir})")
                parsed[key] = {
                    "machine_sections": defaultdict(set),
                    "section_listed_counts": defaultdict(int),
                    "section_unique_sets": defaultdict(set),
                    "entries_listed": 0,
                    "machines_with_multiple_sections": 0,
                    "duplicates_across_sections": 0,
                    "duplicates_within_section": 0,
                    "version": {},
                    "encoding": encodings.get(path.name, "utf-8"),
                }
                continue

            try:
                with zipfile.ZipFile(gh_zip) as zf:
                    members = find_gh_ini_members(zf)
                    member = None
                    if key == "game":
                        member = members.get("game")
                    elif key == "category":
                        member = members.get("category")
                    elif key == "type":
                        member = members.get("type")

                    if not member:
                        raise FileNotFoundError(f"{key} ini not found in {gh_zip.name}")

                    # Write to a temp file for the existing parser
                    enc = encodings.get(path.name, "utf-8")
                    with zf.open(member) as src, tempfile.NamedTemporaryFile("wb", delete=False) as tmp:
                        tmp.write(src.read())
                        tmp_path = Path(tmp.name)

                    ext = parse_ini_file_extended(tmp_path, enc)
                    ext["version"] = ini_version_info(tmp_path, encoding=enc)
                    ext["encoding"] = enc
                    parsed[key] = ext

                    # Clean up the temp file
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

            except Exception as e:
                log.warning(f"Failed to read {key} INI from zip {gh_zip.name}: {e}")
                parsed[key] = {
                    "machine_sections": defaultdict(set),
                    "section_listed_counts": defaultdict(int),
                    "section_unique_sets": defaultdict(set),
                    "entries_listed": 0,
                    "machines_with_multiple_sections": 0,
                    "duplicates_across_sections": 0,
                    "duplicates_within_section": 0,
                    "version": {},
                    "encoding": encodings.get(path.name, "utf-8"),
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

def _temp_extract_inis_from_history_zip(version: str | None) -> dict[str, Path] | None:
    """
    Best-effort: if the three INIs are not present on disk, try to pull them
    from the History ZIP in releases/<ver>/archives and return temp Paths.
    Caller must clean the temp dir (we do it via TemporaryDirectory context).
    """   
    ver = active_version(version)

    # Pick a history zip (simple heuristic: filename contains 'history')
    arcdir = archives_dir(version)
    if not arcdir.exists():
        return None
    candidates = [p for p in arcdir.iterdir()
                  if p.is_file() and p.suffix.lower() == ".zip" and "history" in p.name.lower()]
    if not candidates:
        return None

    # Use the newest history zip
    zip_path = max(candidates, key=lambda p: p.stat().st_mtime)

    # Extract the three INIs into a temp dir
    tmpdir = tempfile.TemporaryDirectory(prefix="mht_inis_")
    td = Path(tmpdir.name)

    extracted = {}
    with zipfile.ZipFile(zip_path) as zf:
        # Use the active/given release version to derive the canonical basenames
        want = {
            ini_game_path(ver).name.lower():      ini_game_path(ver).name,
            ini_category_path(ver).name.lower():  ini_category_path(ver).name,
            ini_type_path(ver).name.lower():      ini_type_path(ver).name,
        }
        # Try to find and extract by leafname match (case-insensitive)
        for zinfo in zf.infolist():
            leaf = Path(zinfo.filename).name.lower()
            if leaf in want:
                outp = td / want[leaf]
                outp.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(zinfo) as src, open(outp, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted[want[leaf]] = outp

    # Only succeed if we got all three (use version-aware names)
    required = {
        ini_game_path(ver).name,
        ini_category_path(ver).name,
        ini_type_path(ver).name,
    }
    if required.issubset(set(extracted.keys())):
        # Return mapping plus a handle to keep the tempdir alive on caller side
        extracted["_tmpdir"] = td  # marker so caller can keep context alive
        extracted["_tmpctx"] = tmpdir
        return extracted

    # Cleanup on failure
    tmpdir.cleanup()
    return None

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
    
    # If any INIs are missing on disk, try to source them from the History ZIP (temp only)
    missing = [p for p in ini_paths if not p.exists()]
    tmp_ctx = None
    if missing:
        # try to infer version from active_version()
        from mht.utils.paths import active_version  # local import to avoid cycles at module import time
        try:
            ver = active_version()           
            global INI_FILES
            INI_FILES = {
                "game_status": ini_game_path(ver),
                "category":    ini_category_path(ver),
                "type":        ini_type_path(ver),
            }            
        except Exception:
            ver = None
        pulled = _temp_extract_inis_from_history_zip(ver)
        if pulled:                                    
            # Use the canonical per-release basenames as the keys to 'pulled'
            k_game = ini_game_path(ver).name
            k_cat  = ini_category_path(ver).name
            k_type = ini_type_path(ver).name

            INI_FILES.update({
                "game_status": pulled[k_game],
                "category":    pulled[k_cat],
                "type":        pulled[k_type],
            })
            ini_paths = list(INI_FILES.values())
            tmp_ctx = pulled.get("_tmpctx")  # keep the context alive until function end
            log.info("Using INIs from history ZIP (temporary extraction).")
        else:
            log.warning("INIs missing on disk and not located in history ZIP; proceeding with empty bundle.")
        
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
        # cleanup temp extract (if any)
        if tmp_ctx:
            tmp_ctx.cleanup()
        return True

    log.error("Failed to write one or more INI outputs; not saving stamp.")
    if tmp_ctx:
        tmp_ctx.cleanup()
    return False
