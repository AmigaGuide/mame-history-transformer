"""
Filename: main.py
Author: XtC

Project:
MAME-History-Transformer — “Adapting MAME and Gaming-History XML metadata for ExoticA’s
Lost in Translation.”

Purpose:
Top-level orchestrator for the pipeline. Verifies required inputs, detects/updates
encodings and source versions (cached in data/encodings.json), runs each stage
with stamp-based skip-unchanged semantics, and writes a per-run manifest.

Pipeline stages (in order):
  1) History INI parse        -> output/gh_ini_classifications.json
  2) MAME XML parse           -> output/mame_machines.json + output/mame_parent_index.json
  3) History XML parse        -> output/gh_system_ports.json
  4) Transform (join/project) -> output/exotica_lit_raw_data.json,
                                 output/exotica_lit_wiki.json,
                                 output/exotica_wiki_pages_and_redirects.json

Key behaviours:
- Required files check (under data/): mame.xml, history.xml, and three GH INIs.
- Encoding/version cache: data/encodings.json (only rewritten on change).
- Stamp-aware execution: downstream modules decide freshness and may skip work.
- Run manifest: data/run_manifest.json (inputs, outputs, hashes, timings, stats).
- Suffix-tolerant version comparison for informational logging.

Inputs & outputs (paths are centralised in mht.utils.paths):
- Inputs: DATA_DIR / "mame.xml", DATA_DIR / "history.xml", and three GH INIs.
- Stage summaries: DATA_DIR / "*_parsing_summary.json".
- Final artefacts: see outputs in the stage list above.

Notes:
- This module is invoked by the CLI (`python -m mht`), but can also be run directly.
- Logging is configured via mht.utils.logger and respects mht.utils.config.LOG_LEVEL.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import zipfile

from mht.utils.config import LOG_LEVEL
from mht.utils.logger import setup_logger, debug_log
from mht.inputs.mame_parser import parse_mame_xml
from mht.inputs.history_xml_parser import parse_history_entries
from mht.inputs.history_ini_parser import parse_history_inis
from mht.transform.pipeline import run_transformer
from mht.utils.paths import (
    # release resolution + dirs
    active_version, archives_dir,

    # per-release inputs (extracted)
    mame_xml_path, history_xml_path,
    ini_game_path, ini_category_path, ini_type_path,

    # per-release stage summaries
    mame_summary_path, history_summary_path, ini_summary_path, transform_summary_path,

    # per-release intermediates/outputs
    mame_machines_path, parent_index_path, gh_system_ports_path, ini_classifications_path,
    exotica_wiki_path, exotica_raw_path, exotica_pages_path, manifest_path,

    # shared
    DATA_DIR, title_overrides_path,
    
    # legacy global cache path (read-only for migration)
    ENCODINGS_JSON,

    # NEW: per-release cache path
    encodings_cache_path,
)

# Public API (this module is intended to be run as a script, but the helpers are importable)
__all__ = [
    "main",
    "check_required_files",
    "get_xml_version",
    "get_ini_version",
    "parse_version_loose",
    "numeric_core_str",
    "same_numeric_core",
    "version_record",
]

log = setup_logger(log_level=LOG_LEVEL)

# ----------------------------
# Version parsing helpers
# ----------------------------

# Suffix-tolerant version regex (e.g. '0.279', '2.79a', '0.279-rc1')
_VERSION_RX = re.compile(
    r"""
    ^\s*
    (?P<num>\d+(?:\.\d+)*)                 # numeric core, e.g. 0.279 or 2.79
    (?P<suffix>[-_.]?[A-Za-z0-9]+          # optional suffix start: a / rc1 / -rev2
        (?:[-_.][A-Za-z0-9]+)*)?           # ... followed by segments
    \s*$
    """,
    re.VERBOSE,
)

def _cached_raw_version(entry: dict[str, Any] | None) -> str | None:
    """
    Return the raw version string from an encodings.json entry.

    Supports both shapes:
      - {"version": {"raw": "...", "numeric_core": "...", "suffix": "..."}}
      - {"version": "..."}  # legacy cache format

    Args:
        entry: The per-file cache entry from encodings.json, or None.

    Returns:
        The raw version string if present, otherwise None.
    """
    if not isinstance(entry, dict):
        return None
    v = entry.get("version")
    if isinstance(v, dict):
        return v.get("raw")
    if isinstance(v, str):
        # legacy: version was stored as a plain string
        return v
    return None

def _entry_differs(prev: dict | None, new: dict | None) -> bool:
    """
    Minimal diff test for encodings.json entries: compare encoding and version.raw.
    """
    prev = prev or {}
    new  = new or {}

    prev_enc = prev.get("encoding")
    new_enc  = new.get("encoding")

    prev_raw = _cached_raw_version(prev)
    new_raw  = _cached_raw_version(new)

    return (prev_enc != new_enc) or (prev_raw != new_raw)

def _history_root_attrs(p: Path, encoding: str = "utf-8") -> dict:
    """
    Read the <history> root attributes (version/date) from history.xml.

    Note:
      The XML parser reads bytes and will honour the XML prolog encoding; the
      'encoding' parameter is advisory and preserved for symmetry with callers.
    """
    try:
        for event, elem in ET.iterparse(p, events=("start",)):
            if elem.tag.lower() == "history":
                return {
                    "history_version": elem.attrib.get("version"),
                    "history_date": elem.attrib.get("date"),
                }
    except Exception:
        pass
    return {}

def _sha256_file(p: Path) -> str:
    """
    Compute a SHA256 digest for the file at `p` in 64 KiB chunks (memory-friendly).
    """
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def _file_meta(p: Path) -> dict:
    """Return a small, cross-platform metadata block for manifest entries."""
    st = p.stat()
    return {
        "path": str(p).replace("\\", "/"),
        "size_bytes": st.st_size,
        "modified_utc": datetime.datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z",
        "sha256": _sha256_file(p),
    }

def _find_history_archive_for_manifest(version: Optional[str]) -> Optional[Path]:
    """Return a representative history ZIP in releases/<ver>/archives to show in the manifest."""
    if not version:
        try:
            version = active_version()
        except Exception:
            return None
    adir = archives_dir(version)
    if not adir.exists():
        return None
    # Prefer obvious history zips, else any zip
    for pat in ("history*.zip", "*.zip"):
        for zp in adir.glob(pat):
            return zp
    return None

def _find_mame_archive_for_manifest(version: Optional[str]) -> Optional[Path]:
    """Return a representative MAME ZIP in releases/<ver>/archives to show in the manifest."""
    if not version:
        try:
            version = active_version()
        except Exception:
            return None
    adir = archives_dir(version)
    if not adir.exists():
        return None
    # Prefer obvious MAME zips, else any zip
    for pat in ("mame*.zip", "*.zip"):
        for zp in adir.glob(pat):
            return zp
    return None
    
def parse_version_loose(s: str) -> Tuple[Tuple[int, ...], Optional[str]]:
    """
    Parse a version string into a numeric core tuple and optional suffix.

    Args:
        s: Raw version string, e.g. '0.279', '2.79a', '0.279-rc1'.

    Returns:
        (numeric_core_tuple, suffix_or_None).
        If unparsable, returns ((), None).
    """
    m = _VERSION_RX.match(s or "")
    if not m:
        return ((), None)
    num = tuple(int(p) for p in m.group("num").split("."))
    suffix = m.group("suffix")
    if suffix:
        suffix = suffix.lstrip("-_.")
    return (num, suffix)

def numeric_core_str(core: Tuple[int, ...]) -> Optional[str]:
    """
    Convert a numeric core tuple into a dotted string, e.g. (0, 279) -> "0.279".
    """
    if not core:
        return None
    return ".".join(str(n) for n in core)

def same_numeric_core(*version_strings: str) -> bool:
    """
    True iff all provided version strings share the same numeric core
    and all are parsable.
    """
    cores = []
    for vs in version_strings:
        core, _ = parse_version_loose(vs)
        if not core:
            return False
        cores.append(core)
    return len(set(cores)) == 1

def version_record(raw: str) -> Dict[str, Optional[str]]:
    """
    Build a structured record for a version string capturing raw, numeric_core, and suffix.
    """
    core, suffix = parse_version_loose(raw or "")
    return {
        "raw": raw,
        "numeric_core": numeric_core_str(core),
        "suffix": suffix,
    }

# ---------------------------------------------------------------------------
# File presence and version extraction
# ---------------------------------------------------------------------------

def check_required_files() -> Optional[List[Path]]:
    """
    Ensure we have usable inputs. We now require:
      - Two ZIP archives staged in releases/<active>/archives:
          * one 'mame*.zip'
          * one 'history*.zip'

    Returns a list of the staged ZIP Paths for logging/manifest, or None if missing.
    """
    from mht.utils.paths import active_version, archives_dir
    try:
        ver = active_version()
    except Exception:
        ver = None

    arc = archives_dir(ver)
    mame_zip = None
    hist_zip = None
    if arc.exists():
        for p in arc.iterdir():
            if p.suffix.lower() == ".zip":
                low = p.name.lower()
                if ("mame" in low) and (mame_zip is None):
                    mame_zip = p
                if ("history" in low) and (hist_zip is None):
                    hist_zip = p

    found: list[Path] = []
    if mame_zip and hist_zip:
        found += [mame_zip, hist_zip]
        log.info("All required inputs present (staged archives).")
        return found

    log.error("Missing required archives in releases/<ver>/archives.")
    log.error("  - Expect one 'mame*.zip' and one 'history*.zip'")
    return None

def get_xml_version(file_path: Path, root_tag: str) -> str:
    """
    Extract a raw version/build string from the root of an XML file.

    Returns:
        The value of 'build' (MAME) or 'version' (History) when found; 'Unknown' or
        'Parse Error' on failure.
    """
    try:
        for event, elem in ET.iterparse(file_path, events=("start",)):
            if elem.tag == root_tag:
                return elem.attrib.get("build") or elem.attrib.get("version", "Unknown")
    except ET.ParseError:
        log.error(f"Parse error reading {file_path}")
        return "Parse Error"
    return "Unknown"

def get_ini_version(file_path: Path, encoding: str) -> str:
    """
    Extract the MAME version from an INI header line.

    Example header:
      ';; [GAMING HISTORY] Game Or No Game.ini for MAME 0.280 (mame0280) generated @ 31/08/2025 ;;'

    We capture the token immediately following 'for MAME ' (e.g., '0.280').
    """
    pat = re.compile(r"for\s+MAME\s+([0-9]+\.[0-9A-Za-z._-]+)")
    try:
        with open(file_path, encoding=encoding, errors="replace") as f:
            for i, line in enumerate(f):
                if i > 10:
                    break
                if "for MAME" in line:
                    m = pat.search(line)
                    if m:
                        return m.group(1)
    except Exception as e:
        log.warning(f"Could not extract version from {file_path.name}: {e}")
    return "Unknown"

# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Orchestrate presence checks, encoding detection, version comparison (suffix-tolerant),
    cache persistence, and the invocation of MAME and History parsers. Writes a
    run manifest capturing per-stage inputs/outputs/timings and basic stats.
    """
    log.info("Starting MAME-History-Transformer pipeline…")

    required_paths = check_required_files()
    if not required_paths:
        log.error("Aborting. Required files missing.")
        return

    # Resolve version once for logs/paths
    ver = active_version()

    # -------------------------------------------------------
    # ZIP-only: Load per-release encodings cache and (re)detect from archives
    # -------------------------------------------------------
    # Resolve the active release and its per-release cache path
    enc_cache_path = encodings_cache_path(ver)

    # Load prior cache (prefer per-release; fall back to legacy global once)
    encoding_cache: Dict[str, Dict[str, Any]] = {}
    migrated_from_legacy = False

    if enc_cache_path.exists():
        try:
            with open(enc_cache_path, "r", encoding="utf-8") as f:
                encoding_cache = json.load(f)
            log.info("Loaded per-release encodings cache: %s", enc_cache_path.as_posix())
        except (json.JSONDecodeError, IOError):
            log.warning("Could not read per-release encodings.json. Will re-detect all files.")
            encoding_cache = {}
    else:
        # One-time legacy migration if a global cache exists
        if ENCODINGS_JSON.exists():
            try:
                with open(ENCODINGS_JSON, "r", encoding="utf-8") as f:
                    encoding_cache = json.load(f)
                migrated_from_legacy = True
                log.info("Migrating legacy global encodings.json to per-release cache.")
            except (json.JSONDecodeError, IOError):
                log.warning("Legacy global encodings.json unreadable; starting with empty cache.")
                encoding_cache = {}
        else:
            encoding_cache = {}

    # Identify the two staged archives selected earlier by check_required_files()
    mame_zip = None
    hist_zip = None
    for p in required_paths:
        if p.suffix.lower() == ".zip":
            if "mame" in p.name.lower() and mame_zip is None:
                mame_zip = p
            if "history" in p.name.lower() and hist_zip is None:
                hist_zip = p
    if not (mame_zip and hist_zip):
        log.error("Expected staged MAME and History archives in releases/<ver>/archives/")
        return

    canonical_leaves = {
        "mame_xml":    "mame.xml",
        "history_xml": "history.xml",
        "ini_game":     "[GAMING HISTORY] Game Or No Game.ini",
        "ini_category": "[GAMING HISTORY] Machine Category.ini",
        "ini_type":     "[GAMING HISTORY] Machine Type.ini",
    }

    from mht.utils.encoding_utils import detect_encodings_from_archives
    encodings_dict, cache_changed = detect_encodings_from_archives(
        mame_archive=mame_zip,
        history_archive=hist_zip,
        canonical_leaves=canonical_leaves,
        prior=encoding_cache,
    )

    # Normalise encodings for downstream modules: {leaf -> "utf-8"/...}
    encodings = {
        leaf: (rec.get("encoding") or "utf-8")
        for leaf, rec in encodings_dict.items()
        if isinstance(rec, dict)
    }

    # Persist per-release cache
    # Always write when:
    #  - the detector says fields changed, or
    #  - we migrated from legacy, or
    #  - the per-release file does not yet exist.
    should_write_cache = cache_changed or migrated_from_legacy or (not enc_cache_path.exists())

    if should_write_cache:
        enc_cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(enc_cache_path, "w", encoding="utf-8") as f:
            json.dump(encodings_dict, f, indent=4, ensure_ascii=False)
        if migrated_from_legacy:
            log.info("Saved per-release encodings.json (initial migration): %s", enc_cache_path.as_posix())
        else:
            log.info("Saved per-release encodings.json (ZIP-only detection): %s", enc_cache_path.as_posix())
    else:
        log.info("Encodings unchanged; reusing per-release cache: %s", enc_cache_path.as_posix())

    #updated_encodings = encodings_dict  # keep your alias for downstream usage

    # Version consistency report (use the raw hints we recorded under xml_root_attrs/ini_header)
    def _raw_version_from_record(leaf: str) -> str:
        rec = encodings_dict.get(leaf) or {}
        # XML: prefer build (MAME) then version (History)
        if leaf in ("mame.xml", "history.xml"):
            xr = (rec.get("xml_root_attrs") or {})
            return xr.get("build") or xr.get("version") or "Unknown"
        # INI: prefer mame_version from header sniff
        ih = (rec.get("ini_header") or {})
        return ih.get("mame_version") or "Unknown"

    mame_ver_raw = _raw_version_from_record("mame.xml")
    hist_ver_raw = _raw_version_from_record("history.xml")
    ini_game_raw = _raw_version_from_record("[GAMING HISTORY] Game Or No Game.ini")
    ini_cat_raw  = _raw_version_from_record("[GAMING HISTORY] Machine Category.ini")
    ini_type_raw = _raw_version_from_record("[GAMING HISTORY] Machine Type.ini")

    all_versions = [mame_ver_raw, hist_ver_raw, ini_game_raw, ini_cat_raw, ini_type_raw]
    if not same_numeric_core(*all_versions):
        log.warning("Version mismatch (numeric core differs): %s", ", ".join(v for v in all_versions if v))
    else:
        suffix_notes = []
        labelled = [
            ("MAME", mame_ver_raw),
            ("History", hist_ver_raw),
            ("GameOrNoGame.ini", ini_game_raw),
            ("MachineCategory.ini", ini_cat_raw),
            ("MachineType.ini", ini_type_raw),
        ]
        for label, v in labelled:
            _, suf = parse_version_loose(v or "")
            if suf:
                suffix_notes.append(f"{label}={v} (suffix '{suf}')")
        if suffix_notes:
            log.info("Detected revision suffixes: %s", "; ".join(suffix_notes))
        else:
            debug_log("All sources share the same numeric core and no suffixes were detected.")

    # Surface noteworthy provider changes
    for leaf in ("mame.xml", "history.xml"):
        rec = encodings_dict.get(leaf) or {}
        decl = rec.get("xml_decl_encoding")
        if decl:
            log.warning(f"{leaf} declares encoding='{decl}' — provider may have changed other things; cache updated.")

    log.info("Proceeding to source file parsing...")

    # Pass encodings to downstream modules (filename -> encoding)
    encodings = {k: v.get("encoding", "utf-8")
                 for k, v in encodings_dict.items()
                 if isinstance(v, dict)}

    # ---------------- HISTORY .ini parse ----------------
    log.info("Beginning History .ini parse...")
    ini_started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    ini_t0 = time.perf_counter()

    ok_ini = parse_history_inis(DATA_DIR, encodings)

    ini_duration = round(time.perf_counter() - ini_t0, 3)
    ini_finished_utc = datetime.datetime.utcnow().isoformat() + "Z"

    # Manifest inputs/outputs metadata for INI stage (ZIP-only)
    ini_summary_fp = ini_summary_path()
    ini_output_fp  = ini_classifications_path()

    # Determine the History ZIP used for INIs
    try:
        ver = active_version()
    except Exception:
        ver = None
    zp = _find_history_archive_for_manifest(ver) if ver else None

    ini_inputs = []
    if zp and zp.exists():
        meta = _file_meta(zp)
        meta["note"] = "streamed INIs from ZIP (no extracted INIs)"

        # Attempt to resolve which members we actually read (by canonical basenames)
        want = {
            ini_game_path().name.lower(),
            ini_category_path().name.lower(),
            ini_type_path().name.lower(),
        }
        try:
            with zipfile.ZipFile(zp) as zf:
                by_leaf = {}
                for zinfo in zf.infolist():
                    leaf = Path(zinfo.filename).name
                    if leaf.lower() in want and leaf.lower() not in by_leaf:
                        by_leaf[leaf.lower()] = zinfo.filename
                if by_leaf:
                    meta["zip_members"] = [by_leaf[k] for k in sorted(by_leaf.keys())]
        except Exception:
            pass

        # Attach visible versions from encodings cache where available (by leaf name)
        meta["sources"] = []
        for leaf in (ini_game_path().name, ini_category_path().name, ini_type_path().name):
            vrec = ((encodings_dict.get(leaf) or {}).get("version") or {})
            src = {"leaf": leaf}
            if vrec:
                src["version"] = {k: vrec[k] for k in ("raw", "numeric_core", "suffix") if vrec.get(k)}
            enc = ((encodings_dict.get(leaf) or {}).get("encoding")) or "utf-8"
            src["encoding"] = enc
            meta["sources"].append(src)

        ini_inputs.append(meta)
    else:
        ini_inputs.append({"path": str(archives_dir(active_version())), "missing": True})

    # Outputs + quick stats (unchanged behaviour)
    ini_outputs = []
    ini_stats = {}

    if ini_summary_fp.exists():
        meta = _file_meta(ini_summary_fp)
        ini_outputs.append(meta)
        try:
            with open(ini_summary_fp, encoding="utf-8") as f:
                _ini_sum = json.load(f)
            umi = (_ini_sum.get("stats") or {}).get("unique_machine_names_indexed")
            if isinstance(umi, int):
                ini_stats["unique_machine_names_indexed"] = umi
        except Exception as e:
            log.debug(f"Could not read INI summary for stats: {e}")

    if ini_output_fp.exists():
        meta = _file_meta(ini_output_fp)
        try:
            with open(ini_output_fp, encoding="utf-8") as f:
                _map = json.load(f)
            meta["records"] = len(_map) if isinstance(_map, dict) else None
        except Exception:
            meta["records"] = None
        ini_outputs.append(meta)

    ini_stage = {
        "stage": "history_ini",
        "ok": bool(ok_ini),
        "started_utc": ini_started_utc,
        "finished_utc": ini_finished_utc,
        "duration_seconds": ini_duration,
        "inputs": ini_inputs,
        "outputs": ini_outputs,
        "stats": ini_stats,
    }
    stage_fragments = [ini_stage]

    # ---------------- MAME parse ----------------
    log.info("Beginning MAME XML canonical parse...")
    mame_started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    mame_t0 = time.perf_counter()

    ok_mame = parse_mame_xml(mame_xml_path(), encodings=encodings, max_records=0)

    mame_duration = round(time.perf_counter() - mame_t0, 3)
    mame_finished_utc = datetime.datetime.utcnow().isoformat() + "Z"

    ver = active_version()

    # Prefer extracted XML if present; otherwise point the manifest at the archive
    mame_input_path = mame_xml_path()
    if not mame_input_path.exists():
        mame_input_path = _find_mame_archive_for_manifest(ver)

    mame_summary_fp = mame_summary_path()
    mame_out_fp     = mame_machines_path()

    mame_stage = {
        "stage": "mame_parse",
        "ok": bool(ok_mame),
        "started_utc": mame_started_utc,
        "finished_utc": mame_finished_utc,
        "duration_seconds": mame_duration,
        "inputs": [],
        "outputs": [],
        "stats": {},
    }

    # Include an input meta if we actually found something (XML or ZIP)
    if mame_input_path and mame_input_path.exists():
        mmeta = _file_meta(mame_input_path)
        # If it's a real XML, add a tiny version hint (optional)
        if mame_input_path.suffix.lower() == ".xml":
            try:
                mbuild = get_xml_version(mame_input_path, "mame")
                if mbuild and mbuild != "Unknown":
                    mmeta["version"] = {"build": mbuild}
            except Exception:
                pass
        mame_stage["inputs"].append(mmeta)

    if mame_summary_fp.exists() and mame_out_fp.exists():
        with open(mame_summary_fp, encoding="utf-8") as f:
            msum = json.load(f)
        mver = {
            "build":      msum.get("mame", {}).get("build"),
            "mameconfig": msum.get("mame", {}).get("mameconfig"),
        }
        if mame_stage["inputs"]:
            mame_stage["inputs"][0]["version"] = {k: v for k, v in mver.items() if v}
            mame_stage["inputs"][0].pop("content", None)

        mout = _file_meta(mame_out_fp)
        mout["summary_path"] = mame_summary_fp.as_posix()
        with open(mame_out_fp, encoding="utf-8") as f:
            m_machines = json.load(f)
        mout["records"] = len(m_machines)
        mame_stage["outputs"].append(mout)

        parent_index_fp = parent_index_path()
        if parent_index_fp.exists():
            mp = _file_meta(parent_index_fp)
            try:
                with open(parent_index_fp, encoding="utf-8") as f:
                    idx = json.load(f)
                mp["records"] = len(idx.get("parents", {})) if isinstance(idx, dict) else None
            except Exception:
                mp["records"] = None
            mame_stage["outputs"].append(mp)

        t = msum.get("totals", {})
        mame_stage["stats"] = {
            "total_machines":         t.get("total_machines"),
            "total_parents":          t.get("total_parents"),
            "total_clones":           t.get("total_clones"),
            "total_isbios":           t.get("total_isbios"),
            "total_isdevice":         t.get("total_isdevice"),
            "total_ismechanical":     t.get("total_ismechanical"),
            "total_requires_samples": t.get("total_requires_samples"),
        }

    stage_fragments.append(mame_stage)

    
    # ---------------- HISTORY parse ----------------
    log.info("Beginning History XML parse...")
    history_started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    hist_t0 = time.perf_counter()

    history_xml     = history_xml_path()
    hist_summary_fp = history_summary_path()
    gh_out_fp       = gh_system_ports_path()

    # Build a stable "input" meta for the history stage
    try:
        if history_xml.exists():
            history_input_meta = _file_meta(history_xml)
        else:
            try:
                ver = active_version()
            except Exception:
                ver = None
            zp = None
            if ver:
                adir = archives_dir(ver)
                if adir.exists():
                    for cand in sorted(adir.glob("history*.zip")):
                        if cand.exists():
                            zp = cand
                            break
            if zp:
                history_input_meta = _file_meta(zp)
                history_input_meta["note"] = "streamed XML from ZIP (no extracted history.xml)"
            else:
                history_input_meta = {"path": str(history_xml), "missing": True}
    except Exception:
        history_input_meta = {"path": str(history_xml), "missing": True}

    if ok_mame:
        ok_history = parse_history_entries(history_xml, encodings.get("history.xml", "utf-8"))
        hist_errs = []
    else:
        ok_history = False
        hist_errs = ["skipped: mame_parse failed"]
        log.error("History parse skipped because MAME parse failed.")

    history_duration = round(time.perf_counter() - hist_t0, 3)
    history_finished_utc = datetime.datetime.utcnow().isoformat() + "Z"

    history_stage = {
        "stage": "history_xml",
        "ok": bool(ok_history),
        "started_utc": history_started_utc,
        "finished_utc": history_finished_utc,
        "duration_seconds": history_duration,
        "inputs": [history_input_meta],
        "outputs": [],
        "stats": {},
    }
    if hist_errs:
        history_stage["errors"] = hist_errs

    if hist_summary_fp.exists() and gh_out_fp.exists():
        with open(hist_summary_fp, encoding="utf-8") as f:
            hsum = json.load(f)
        totals = hsum.get("totals", {})
        systems_total  = totals.get("systems_total")
        software_total = totals.get("software_total") or 0
        entries_total  = (systems_total or 0) + (software_total or 0)

        # Attach version only if we have a physical XML file path
        try:
            if (not history_input_meta.get("missing")
                and str(history_input_meta.get("path", "")).lower().endswith(".xml")):
                hx = _history_root_attrs(Path(history_input_meta["path"]),
                                         encoding=encodings.get("history.xml", "utf-8"))
                if hx:
                    history_stage["inputs"][0]["version"] = {k: v for k, v in hx.items() if v}
        except Exception:
            pass

        hout = _file_meta(gh_out_fp)
        hout["summary_path"] = hist_summary_fp.as_posix()
        try:
            with open(gh_out_fp, encoding="utf-8") as f:
                gh_data = json.load(f)
            hout["records"] = len(gh_data)
        except Exception:
            hout["records"] = None
        history_stage["outputs"].append(hout)

        history_stage["stats"].update({
            "systems_total":        systems_total,
            "software_total":       software_total,
            "entries_total":        entries_total,
            "systems_with_ports":   totals.get("systems_with_ports"),
            "systems_with_aliases": totals.get("systems_with_aliases"),
            "port_lines_parsed":    totals.get("port_lines_parsed"),
            "ports_with_comments":  totals.get("ports_with_comments"),
        })

    stage_fragments.append(history_stage)


    # ---------------- TRANSFORM ----------------
    log.info("Beginning transform...")
    transform_started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    tr_t0 = time.perf_counter()

    # Run the transformer (it will do its own stamp check and save transform.json on success)
    ok_transform = run_transformer()

    transform_duration = round(time.perf_counter() - tr_t0, 3)
    transform_finished_utc = datetime.datetime.utcnow().isoformat() + "Z"

    # Collect inputs for the manifest (what transform *read*)
    tr_inputs = []
    for inp in (
        mame_machines_path(),
        ini_classifications_path(),
        parent_index_path(),
        gh_system_ports_path(),
        title_overrides_path(),     # may not exist; that’s fine
    ):
        if inp.exists():
            tr_inputs.append(_file_meta(inp))

    # Collect outputs for the manifest (what transform *wrote*)
    tr_outputs = []
    tr_stats = {}

    wiki_fp = exotica_wiki_path()
    if wiki_fp.exists():
        wmeta = _file_meta(wiki_fp)
        try:
            with open(wiki_fp, encoding="utf-8") as f:
                wiki_doc = json.load(f)
            wmeta["records"] = len((wiki_doc or {}).get("games", {}))
        except Exception:
            wmeta["records"] = None
        tr_outputs.append(wmeta)

    tr_summary_fp = transform_summary_path()
    if tr_summary_fp.exists():
        smeta = _file_meta(tr_summary_fp)
        tr_outputs.append(smeta)
        try:
            with open(tr_summary_fp, encoding="utf-8") as f:
                ts = json.load(f)
            c = (ts or {}).get("counts", {})
            tr_stats.update({
                "eligible_parents": c.get("eligible_parents"),
                "final_included": c.get("final_included"),
                "clones_included_unknown_classification": c.get("clones_included_unknown_classification"),
            })
        except Exception:
            pass

    raw_fp = exotica_raw_path()
    if raw_fp.exists():
        rmeta = _file_meta(raw_fp)
        try:
            with open(raw_fp, encoding="utf-8") as f:
                raw_doc = json.load(f)
            rmeta["records"] = len((raw_doc or {}).get("games", {}))
        except Exception:
            rmeta["records"] = None
        tr_outputs.append(rmeta)

    pages_fp = exotica_pages_path()
    if pages_fp.exists():
        pmeta = _file_meta(pages_fp)
        tr_outputs.append(pmeta)
        try:
            with open(pages_fp, encoding="utf-8") as f:
                pages_doc = json.load(f)
            tr_stats.update({
                "wiki_pages_count":     len((pages_doc or {}).get("pages", [])),
                "wiki_redirects_count": len((pages_doc or {}).get("redirects", [])),
                "wiki_conflicts_count": len((pages_doc or {}).get("conflicts", [])),
            })
        except Exception:
            pass

    transform_stage = {
        "stage": "transform",
        "ok": bool(ok_transform),
        "started_utc": transform_started_utc,
        "finished_utc": transform_finished_utc,
        "duration_seconds": transform_duration,
        "inputs": tr_inputs,
        "outputs": tr_outputs,
        "stats": tr_stats,
    }

    stage_fragments.append(transform_stage)


    # ---------------- Manifest ----------------
    started_candidates  = [s.get("started_utc")  for s in stage_fragments if s.get("started_utc")]
    finished_candidates = [s.get("finished_utc") for s in stage_fragments if s.get("finished_utc")]

    run_started  = min(started_candidates)  if started_candidates  else datetime.datetime.utcnow().isoformat() + "Z"
    run_finished = max(finished_candidates) if finished_candidates else datetime.datetime.utcnow().isoformat() + "Z"

    # Encoding cache meta for the manifest
    enc_cache_meta = {"path": enc_cache_path.as_posix()}
    try:
        if enc_cache_path.exists():
            enc_cache_meta["sha256"] = _sha256_file(enc_cache_path)
            enc_cache_meta["size_bytes"] = enc_cache_path.stat().st_size
    except Exception:
        pass

    manifest = {
        "schema_version": 1,
        "run_id": datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        "started_utc": run_started,
        "finished_utc": run_finished,
        "encoding_cache": enc_cache_meta,
        "stages": stage_fragments,
    }

    mp = manifest_path()  # data/releases/<ver>/manifest.json
    mp.parent.mkdir(parents=True, exist_ok=True)
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    log.info(f"Wrote {mp.as_posix()}")

    try:
        from mht.provenance.releases_index import rebuild_releases_index
        rebuild_releases_index()
    except Exception as ex:
        print(f"Error rebuilding releases index: {ex}")
        raise  # Optionally raise the exception to stop the pipeline


if __name__ == "__main__":
    main()
