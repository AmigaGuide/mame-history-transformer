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
from typing import Dict, Any
import time
import datetime
import zipfile
import io
import json

from mht.utils.config import LOG_LEVEL
from mht.utils.logger import setup_logger, debug_log
from mht.utils.stamps import save_stamp, stage_is_fresh
from mht.utils.paths import (
    ini_game_path, ini_category_path, ini_type_path,
    ini_summary_path, ini_classifications_path,
    encodings_cache_path,
    archives_dir, active_version,
)
from mht.utils.io import write_json, file_meta
from mht.utils.ini import (
    ini_version_info,
    parse_ini_file_extended,
)
from mht.inputs.ini_summary import build_ini_summary
from mht.utils.records import build_ini_class_map
from mht.utils.validator import validate_ini_parsed_bundle
from mht.utils.encoding_utils import load_encodings_cache


log = setup_logger(log_level=LOG_LEVEL)

# Output normalisation
GAME_STATUS_MAP = {"Game": "game", "No Game": "no_game"}
UNKNOWN = "unknown"


__all__ = [
    "parse_history_inis",
    "load_ini_classifications",
]


# --- ZIP-only helpers ---------------------------------------------------------

def _pick_history_zip(version: str) -> Path:
    """Return the preferred History ZIP for this release, or raise FileNotFoundError."""
    arc_dir = archives_dir(version)
    if not arc_dir.exists():
        raise FileNotFoundError(f"Archives folder missing: {arc_dir.as_posix()}")
    # Prefer files with 'history' in the name; else any .zip
    zips = sorted([p for p in arc_dir.iterdir() if p.suffix.lower() == ".zip"], key=lambda p: p.name.lower())
    hist = [p for p in zips if "history" in p.name.lower()] or zips
    if not hist:
        raise FileNotFoundError(f"No .zip files found under {arc_dir.as_posix()}")
    return hist[0]


def _enc_for_ini_basename(encodings: Dict[str, str], basename: str) -> str:
    """
    Our encoding cache is keyed by filename (leaf). Look up by the canonical
    basename the project uses (e.g. '[GAMING HISTORY] Machine Type.ini').
    """
    return encodings.get(basename, "utf-8")


def _want_ini_basenames(version: str) -> dict[str, tuple[str, str]]:
    """
    Map logical keys -> (canonical basename, manifest_label).
    Keys used downstream: 'game_status', 'category', 'type'
    """
    return {
        "game_status": (ini_game_path(version).name,     "Game Or No Game.ini"),
        "category":    (ini_category_path(version).name, "Machine Category.ini"),
        "type":        (ini_type_path(version).name,     "Machine Type.ini"),
    }

# --------------------------------------------------------------------------------------
# Public pure workers (ZIP-only)
# --------------------------------------------------------------------------------------

def load_ini_classifications(encodings: Dict[str, str],
                             ini_paths: dict[str, Path] | None = None) -> Dict[str, dict]:
    """
    ZIP-only variant: ignore ini_paths; always stream the three INIs from the
    History ZIP in the active release.

    Returns the same 'parsed bundle' shape as before.
    """
    t0 = time.perf_counter()
    parsed: Dict[str, dict] = {}

    ver = active_version()
    zip_path = _pick_history_zip(ver)

    want = _want_ini_basenames(ver)  # {key -> (basename, label)}
    with zipfile.ZipFile(zip_path) as zf:
        # Build a case-insensitive lookup of members by leafname
        by_leaf = {}
        for zinfo in zf.infolist():
            leaf = Path(zinfo.filename).name
            by_leaf.setdefault(leaf.lower(), zinfo.filename)

        for key, (basename, _label) in want.items():
            member = by_leaf.get(basename.lower())
            if not member:
                log.warning(f"Missing INI in ZIP {zip_path.name}: {basename}")
                parsed[key] = {
                    "machine_sections": defaultdict(set),
                    "section_listed_counts": defaultdict(int),
                    "section_unique_sets": defaultdict(set),
                    "entries_listed": 0,
                    "machines_with_multiple_sections": 0,
                    "duplicates_across_sections": 0,
                    "duplicates_within_section": 0,
                    "version": {},
                    "encoding": _enc_for_ini_basename(encodings, basename),
                }
                continue

            enc = _enc_for_ini_basename(encodings, basename)

            # Parse body
            with zf.open(member, "r") as bf:
                text = io.TextIOWrapper(bf, encoding=enc, errors="replace")
                ext = parse_ini_file_extended(text)   # stream path; encoding handled by wrapper

            # Parse header/version (fresh stream)
            with zf.open(member, "r") as bf2:
                text2 = io.TextIOWrapper(bf2, encoding=enc, errors="replace")
                ext["version"] = ini_version_info(text2)  # stream again for header sniff

            ext["encoding"] = enc
            parsed[key] = ext

            debug_log(
                f"[ini] {basename}: entries_listed={ext.get('entries_listed')}, "
                f"unique_names_total={sum(len(s) for s in ext.get('section_unique_sets', {}).values())}"
            )

    log.info(f"INI classification data loaded from ZIP in {time.perf_counter() - t0:.2f} seconds")
    return parsed


# --------------------------------------------------------------------------------------
# Orchestrator (I/O + stamps) — ZIP-only
# --------------------------------------------------------------------------------------

def _ini_input_from_cache(cache: dict[str, Any], leaf: str, kind: str) -> dict[str, Any]:
    """
    Build a rich input block for a single INI from encodings.json.
    `leaf` must be the canonical basename your pipeline uses.
    """
    rec = cache.get(leaf) or {}
    return {
        "kind": kind,                                   # e.g. 'ini_game'
        "leaf": leaf,
        "encoding": rec.get("encoding") or "utf-8",
        "ascii_only": bool(rec.get("ascii_only")),
        "detected_via": rec.get("detected_via"),
        "zip_archive": rec.get("zip_archive"),
        "zip_member": rec.get("zip_member"),
        "zip_crc32": rec.get("zip_crc32"),
        "zip_size_bytes": rec.get("zip_size_bytes"),
        # Optional version/header hints if present
        "version_hint": (rec.get("ini_header") or {}),
    }

def parse_history_inis(data_dir: Path, encodings: Dict[str, str]) -> bool:
    """
    ZIP-only orchestrator for the History INI stage:
      - Resolves the History ZIP for the active release.
      - Streams all three INIs directly from the archive (no temp extraction).
      - Writes summary and classifications outputs.
      - Stamps using the ZIP file and encodings.json as inputs.
    """
    t0 = time.perf_counter()
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"

    ver = active_version()
    zip_path = _pick_history_zip(ver)          # raises if not found
    primary_input = zip_path                   # zip-only: always the archive
    enc_path = encodings_cache_path(ver)       # data/releases/<ver>/encodings.json

    fresh, stamp_path, current_stamp = stage_is_fresh(
        "ini.json",
        schema_id="mht.stage.ini",
        tool="ini_summary",
        inputs=[primary_input, enc_path],
    )

    if fresh:
        log.info("INI stage up-to-date (stamp matched) — skipping rebuild")
        return True

    # Parse bundle (pure)
    parsed = load_ini_classifications(encodings)

    # Warnings-only invariants
    ini_issues = validate_ini_parsed_bundle(parsed, log)
    if ini_issues == 0:
        debug_log("[history_ini_parser] INI invariants passed (ZIP-only)")

    # Build docs
    summary   = build_ini_summary(parsed, now_iso)
    class_map = build_ini_class_map(parsed)

    # Write
    ok_summary = write_json(ini_summary_path(), summary, sort_keys=False)
    ok_output  = write_json(ini_classifications_path(), class_map, sort_keys=True)

    if ok_summary and ok_output:           
        # ---- Build a rich stamp while preserving the freshness core from current_stamp
        stamp_doc = dict(current_stamp)  # keep keys stage_is_fresh expects

        # Inputs (three INIs) from encodings cache
        enc_cache_path = encodings_cache_path(ver)  # data/releases/<ver>/encodings.json
        enc_cache_file = load_encodings_cache(enc_cache_path)
        leaf_game      = ini_game_path(ver).name
        leaf_category  = ini_category_path(ver).name
        leaf_type      = ini_type_path(ver).name

        inputs_detail = [
            _ini_input_from_cache(enc_cache_file, leaf_game, kind="ini_game"),
            _ini_input_from_cache(enc_cache_file, leaf_category, kind="ini_category"),
            _ini_input_from_cache(enc_cache_file, leaf_type, kind="ini_type"),
        ]
                        
        # Outputs meta
        out_summary_fp = ini_summary_path()
        out_class_fp   = ini_classifications_path()
        outputs = []
        if out_summary_fp.exists():
            smeta = file_meta(out_summary_fp)
            outputs.append(smeta)
        if out_class_fp.exists():
            ometa = file_meta(out_class_fp)
            # Include a light record count for convenience
            try:
                with open(out_class_fp, "r", encoding="utf-8") as f:
                    m = json.load(f)
                ometa["records"] = len(m) if isinstance(m, dict) else None
            except Exception:
                ometa["records"] = None
            outputs.append(ometa)

        # Stats (lift from the summary we just built)
        stats = {}
        try:
            stats = summary.get("stats", {}) if isinstance(summary, dict) else {}
        except Exception:
            stats = {}

        # Attach enrichments (additive keys so stage_is_fresh comparisons remain stable)
        stamp_doc["created_utc"] = now_iso
        stamp_doc["inputs_detail"] = inputs_detail
        stamp_doc["outputs"] = outputs
        stamp_doc["stats"] = stats

        save_stamp(stamp_path, stamp_doc)

        duration = time.perf_counter() - t0
        log.info(
            f"INI parsing completed in {duration:.2f}s (streamed from {zip_path.name}); "
            f"ok_summary={ok_summary}, ok_output={ok_output}"
        )
        return True

    log.error("Failed to write one or more INI outputs; not saving stamp.")
    return False
