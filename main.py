"""
Filename: main.py
Version: 1.0.0
Last modified: 2025-09-11
Author: Jason (XtC) Skelly (Open University TM470, 2025)

Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Purpose:
Entry point for the XML parsing and classification pipeline. Validates the presence
of required source files, detects encodings, verifies version consistency (tolerant
to revision suffixes), writes/updates a run manifest, and orchestrates the three
pipeline phases:
  1) History INI parse -> machine-centric classifications
  2) MAME XML parse    -> canonical machine list + parent index
  3) History XML parse -> structured PORTS data and audits

Outputs (indirect, via called modules):
- data/encodings.json (written when changes detected)
- data/history_parsing_summary.json
- data/ini_parsing_summary.json
- data/mame_parsing_summary.json
- data/run_manifest.json (always written for the run)
- data/transform_summary.json (on successful transform)
- output/exotica_lit_raw_data.json (on successful transform)
- output/exotica_lit_wiki.json (on successful transform)
- output/exotica_wiki_pages_and_redirects.json (on successful transform)
- output/gh_ini_classifications.json
- output/gh_system_ports.json
- output/mame_machines.json
- output/mame_parent_index.json

Licence:
This file forms part of a student project and is not intended for commercial use.
See repository LICENCE for details.
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

from config import LOG_LEVEL
from logger import setup_logger, debug_log
from encoding_utils import detect_encoding
from mame_parser import parse_mame_xml
from history_parser import parse_history_entries
from history_metadata import parse_history_inis
from transformer import run_transformer

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

# Cache file for per-source encodings + versions
ENCODINGS_PATH = Path("data/encodings.json")

# Note: kept for traceability; not used by other modules.
ok_mame = False
ok_history = False


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
    Ensure all required XML/INI files exist in /data. If any are missing,
    log actionable instructions and return None; otherwise return a list of Paths.
    """
    data_dir = Path("data")
    filenames = [
        "mame.xml",
        "history.xml",
        "[GAMING HISTORY] Game Or No Game.ini",
        "[GAMING HISTORY] Machine Category.ini",
        "[GAMING HISTORY] Machine Type.ini",
    ]
    missing = [f for f in filenames if not (data_dir / f).is_file()]

    for fname in filenames:
        if fname not in missing:
            debug_log(f"Verified: data/{fname} exists")

    if missing:
        log.error("Missing required files in /data:")
        for fname in missing:
            log.error(f" - {fname}")

        # Minimal, practical guidance for each case
        log.info("Instructions:")
        if "mame.xml" in missing:
            log.info("• Download MAME XML from https://www.mamedev.org/release.php")
            log.info("• Extract and rename it to 'mame.xml' in the 'data' folder")
        if "history.xml" in missing:
            log.info("• Download Gaming-History XML from arcade-history.com")
            log.info("• Extract 'history.xml' to the 'data' folder")
        if any(".ini" in f for f in missing):
            log.info("• The same ZIP includes .ini files — extract all three to the 'data' folder.")

        return None

    log.info("All required files found.")
    return [data_dir / f for f in filenames]

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
                if i > 10: # headers live at the top; read a handful of lines only
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
    log.info("Starting TM470 XML parsing pipeline...")

    required_paths = check_required_files()
    if not required_paths:
        log.error("Aborting. Required files missing.")
        return

    data_dir = Path("data")

    # -------------------------------------------------------
    # Load existing encodings.json (cache of {encoding,version})
    # -------------------------------------------------------
    encoding_cache: Dict[str, Dict[str, Any]] = {}
    if ENCODINGS_PATH.exists():
        try:
            with open(ENCODINGS_PATH, "r", encoding="utf-8") as f:
                encoding_cache = json.load(f)
            log.info("Loaded encoding cache from encodings.json")
        except (json.JSONDecodeError, IOError):
            log.warning("Could not read encodings.json. Will re-parse all files.")
            encoding_cache = {}

    def _versions_differ(prev_raw: str | None, curr_raw: str | None) -> bool:
        """
        True if the two raw version strings differ after normalising None to "".

        Purpose:
            Cheap change detector for cache invalidation. This does not interpret
            numeric cores or suffixes—see same_numeric_core/parse_version_loose for that.

        Returns:
            bool: Whether the strings differ.
        """
        return (prev_raw or "") != (curr_raw or "")

    updated_encodings: Dict[str, Dict[str, Any]] = dict(encoding_cache)
    cache_changed = False

    # -------------------------------------------------------
    # Read CURRENT header versions (using cached encodings when possible)
    # Decide per-file whether to re-detect encoding.
    # -------------------------------------------------------
    current_versions: Dict[str, str] = {}
    for file_path in required_paths:
        fname = file_path.name
        prev_entry = encoding_cache.get(fname) or {}
        prev_raw = _cached_raw_version(prev_entry)

        if fname.endswith(".xml"):
            # XML: versions live on the root element; no encoding needed to read attributes.
            root_tag = "mame" if "mame" in fname.lower() else "history"
            curr_raw = get_xml_version(file_path, root_tag)
            debug_log(f"[versions] XML {fname}: current_raw={curr_raw!r}")
            current_versions[fname] = curr_raw

        elif fname.endswith(".ini"):
            # INI: to read the header line, use cached encoding if available, else detect once.
            cached_enc = prev_entry.get("encoding")
            enc_used = cached_enc or detect_encoding(file_path)
            debug_log(f"[versions] INI {fname}: reading header with encoding {enc_used!r}")
            curr_raw = get_ini_version(file_path, enc_used)
            debug_log(f"[versions] INI {fname}: prev_raw={prev_raw!r}, curr_raw={curr_raw!r}")
            current_versions[fname] = curr_raw

        else:
            curr_raw = "Unknown"
            current_versions[fname] = curr_raw
            debug_log(f"[versions] {fname}: unsupported extension, curr_raw='Unknown'")

        debug_log(f"[versions] Compare {fname}: prev_raw={prev_raw!r} vs curr_raw={curr_raw!r} "
                  f"-> changed={_versions_differ(prev_raw, curr_raw)}")

    # -------------------------------------------------------
    # Re-detect encodings ONLY where version changed or cache is missing.
    # -------------------------------------------------------
    for file_path in required_paths:
        fname = file_path.name
        prev_entry = encoding_cache.get(fname) or {}
        prev_raw = _cached_raw_version(prev_entry)
        curr_raw = current_versions.get(fname)

        needs_redetect = (prev_entry == {}) or _versions_differ(prev_raw, curr_raw)

        if fname.endswith(".xml"):
            if needs_redetect:
                enc = detect_encoding(file_path)
                vrec = version_record(curr_raw or "Unknown")
                updated_encodings[fname] = {"encoding": enc, "version": vrec}
                cache_changed = True
                debug_log(f"[encodings] XML {fname}: version changed or new. "
                          f"detected_encoding={enc!r}, version={vrec}")
            else:
                if prev_entry:
                    updated_encodings[fname] = prev_entry
                else:
                    enc = detect_encoding(file_path)
                    vrec = version_record(curr_raw or "Unknown")
                    updated_encodings[fname] = {"encoding": enc, "version": vrec}
                    cache_changed = True
                    debug_log(f"[encodings] XML {fname}: no prior cache; detected "
                              f"encoding={enc!r}, version={vrec}")

        elif fname.endswith(".ini"):
            if needs_redetect:
                enc = detect_encoding(file_path)
                curr_raw = get_ini_version(file_path, enc)
                vrec = version_record(curr_raw or "Unknown")
                updated_encodings[fname] = {"encoding": enc, "version": vrec}
                cache_changed = True
                debug_log(f"[encodings] INI {fname}: version changed or new. "
                          f"detected_encoding={enc!r}, version={vrec}")
            else:
                if prev_entry:
                    updated_encodings[fname] = prev_entry
                else:
                    enc = detect_encoding(file_path)
                    curr_raw = get_ini_version(file_path, enc)
                    vrec = version_record(curr_raw or "Unknown")
                    updated_encodings[fname] = {"encoding": enc, "version": vrec}
                    cache_changed = True
                    debug_log(f"[encodings] INI {fname}: seeded cache with "
                              f"encoding={enc!r}, version={vrec}")

        else:
            # Unknown extension: carry forward prior or seed minimally
            if prev_entry:
                updated_encodings[fname] = prev_entry
            else:
                updated_encodings[fname] = {"encoding": "utf-8", "version": version_record("Unknown")}
                cache_changed = True

    # -------------------------------------------------------
    # Persist encodings.json ONLY if changes were made
    # -------------------------------------------------------
    if cache_changed:
        with open(ENCODINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(updated_encodings, f, indent=4)
        log.info("Saved updated encodings.json (changes detected).")
    else:
        log.info("Encodings unchanged; skipped writing encodings.json.")

    # ------------------------------
    # Version consistency reporting
    # ------------------------------
    mame_ver_raw = (updated_encodings.get("mame.xml", {})        .get("version", {}) or {}).get("raw", "Unknown")
    hist_ver_raw = (updated_encodings.get("history.xml", {})     .get("version", {}) or {}).get("raw", "Unknown")
    ini_game_raw = (updated_encodings.get("[GAMING HISTORY] Game Or No Game.ini", {}) .get("version", {}) or {}).get("raw", "Unknown")
    ini_cat_raw  = (updated_encodings.get("[GAMING HISTORY] Machine Category.ini", {}) .get("version", {}) or {}).get("raw", "Unknown")
    ini_type_raw = (updated_encodings.get("[GAMING HISTORY] Machine Type.ini", {})     .get("version", {}) or {}).get("raw", "Unknown")

    all_versions = [mame_ver_raw, hist_ver_raw, ini_game_raw, ini_cat_raw, ini_type_raw]
    if not same_numeric_core(*all_versions):
        log.warning("Version mismatch (numeric core differs): %s", ", ".join(v for v in all_versions if v))
    else:
        # Report any revision suffixes found (informational)
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

    log.info("Proceeding to source file parsing...")

    # Pass encodings to downstream modules (filename -> encoding)
    encodings = {k: v.get("encoding", "utf-8")
                 for k, v in updated_encodings.items()
                 if isinstance(v, dict)}

    # ---------------- HISTORY .ini parse ----------------
    log.info("Beginning History .ini parse...")
    ini_started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    ini_t0 = time.perf_counter()

    ok_ini = parse_history_inis(data_dir, encodings)

    ini_duration = round(time.perf_counter() - ini_t0, 3)
    ini_finished_utc = datetime.datetime.utcnow().isoformat() + "Z"

    # Manifest inputs/outputs metadata for INI stage (index only, not detailed stats)
    ini_summary_path = Path("data/ini_parsing_summary.json")
    ini_output_path  = Path("output/gh_ini_classifications.json")

    ini_inputs = []
    for fname in (
        "[GAMING HISTORY] Game Or No Game.ini",
        "[GAMING HISTORY] Machine Category.ini",
        "[GAMING HISTORY] Machine Type.ini",
    ):
        p = data_dir / fname
        if p.exists():
            ini_inputs.append(_file_meta(p))
        else:
            log.warning(f"INI missing: {fname}")


    # Attach INI versions to inputs (from updated_encodings) for manifest readability
    for meta in ini_inputs:
        fname = Path(meta["path"]).name
        vrec = ((updated_encodings.get(fname) or {}).get("version") or {})
        if vrec:
            meta["version"] = {
                k: vrec[k] for k in ("raw", "numeric_core", "suffix") if vrec.get(k)
            }
        else:
            enc = ((updated_encodings.get(fname) or {}).get("encoding")) or "utf-8"
            try:
                raw = get_ini_version(data_dir / fname, enc)
            except Exception:
                raw = "Unknown"
            core, suf = parse_version_loose(raw or "")
            meta["version"] = {"raw": raw}
            if core: meta["version"]["numeric_core"] = numeric_core_str(core)
            if suf:  meta["version"]["suffix"] = suf

    ini_outputs = []
    ini_stats = {}
    if ini_summary_path.exists():
        meta = _file_meta(ini_summary_path)
        ini_outputs.append(meta)
        try:
            with open(ini_summary_path, encoding="utf-8") as f:
                _ini_sum = json.load(f)
            umi = (_ini_sum.get("stats") or {}).get("unique_machine_names_indexed")
            if isinstance(umi, int):
                ini_stats["unique_machine_names_indexed"] = umi
        except Exception as e:
            log.debug(f"Could not read INI summary for stats: {e}")

    if ini_output_path.exists():
        meta = _file_meta(ini_output_path)
        try:
            with open(ini_output_path, encoding="utf-8") as f:
                _map = json.load(f)
            meta["records"] = len(_map) if isinstance(_map, dict) else None
        except Exception:
            meta["records"] = None
        ini_outputs.append(meta)

    ini_stage = {
        "stage": "history_metadata",
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
    ok_mame = parse_mame_xml(data_dir / "mame.xml", encodings=encodings, max_records=0)
    mame_duration = round(time.perf_counter() - mame_t0, 3)
    mame_finished_utc = datetime.datetime.utcnow().isoformat() + "Z"

    mame_xml          = data_dir / "mame.xml"
    mame_summary_path = Path("data/mame_parsing_summary.json")
    mame_out_path     = Path("output/mame_machines.json")

    mame_stage = {
        "stage": "mame_parse",
        "ok": bool(ok_mame),
        "started_utc": mame_started_utc,
        "finished_utc": mame_finished_utc,
        "duration_seconds": mame_duration,
        "inputs": [_file_meta(mame_xml)],
        "outputs": [],
        "stats": {},
    }

    if mame_summary_path.exists() and mame_out_path.exists():
        with open(mame_summary_path, encoding="utf-8") as f:
            msum = json.load(f)
        mver = {
            "build":      msum.get("mame", {}).get("build"),
            "mameconfig": msum.get("mame", {}).get("mameconfig"),
        }
        mame_stage["inputs"][0]["version"] = {k: v for k, v in mver.items() if v}
        mame_stage["inputs"][0].pop("content", None)

        mout = _file_meta(mame_out_path)
        mout["summary_path"] = mame_summary_path.as_posix()
        with open(mame_out_path, encoding="utf-8") as f:
            m_machines = json.load(f)
        mout["records"] = len(m_machines)
        mame_stage["outputs"].append(mout)

        mame_parent_idx_path = Path("output/mame_parent_index.json")
        if mame_parent_idx_path.exists():
            mp = _file_meta(mame_parent_idx_path)
            try:
                with open(mame_parent_idx_path, encoding="utf-8") as f:
                    idx = json.load(f)
                mp["records"] = len(idx.get("parents", {})) if isinstance(idx, dict) else None
            except Exception:
                mp["records"] = None
            mame_stage["outputs"].append(mp)

        t = msum.get("totals", {})
        mame_stage["stats"] = {
            "total_machines":        t.get("total_machines"),
            "total_parents":         t.get("total_parents"),
            "total_clones":          t.get("total_clones"),
            "total_isbios":          t.get("total_isbios"),
            "total_isdevice":        t.get("total_isdevice"),
            "total_ismechanical":    t.get("total_ismechanical"),
            "total_requires_samples": t.get("total_requires_samples"),
        }

    stage_fragments.append(mame_stage)

    # ---------------- HISTORY parse ----------------
    log.info("Beginning History XML parse...")
    history_started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    hist_t0 = time.perf_counter()

    history_xml        = data_dir / "history.xml"
    hist_summary_path  = Path("data/history_parsing_summary.json")
    gh_out_path        = Path("output/gh_system_ports.json")

    if ok_mame:
        ok_history = parse_history_entries(data_dir / "history.xml", encodings.get("history.xml", "utf-8"))
        hist_errs = []
    else:
        ok_history = False
        hist_errs = ["skipped: mame_parse failed"]
        log.error("History parse skipped because MAME parse failed.")

    history_duration = round(time.perf_counter() - hist_t0, 3)
    history_finished_utc = datetime.datetime.utcnow().isoformat() + "Z"

    history_stage = {
        "stage": "history_parse",
        "ok": bool(ok_history),
        "started_utc": history_started_utc,
        "finished_utc": history_finished_utc,
        "duration_seconds": history_duration,
        "inputs": [_file_meta(history_xml)],
        "outputs": [],
        "stats": {},
    }
    if hist_errs:
        history_stage["errors"] = hist_errs

    if hist_summary_path.exists() and gh_out_path.exists():
        with open(hist_summary_path, encoding="utf-8") as f:
            hsum = json.load(f)
        totals = hsum.get("totals", {})
        systems_total  = totals.get("systems_total")
        software_total = totals.get("software_total") or 0
        entries_total  = (systems_total or 0) + (software_total or 0)

        hx = _history_root_attrs(history_xml, encoding=encodings.get("history.xml", "utf-8"))
        history_stage["inputs"][0]["version"] = {k: v for k, v in hx.items() if v}

        hout = _file_meta(gh_out_path)
        hout["summary_path"] = hist_summary_path.as_posix()
        try:
            with open(gh_out_path, encoding="utf-8") as f:
                gh_data = json.load(f)
            hout["records"] = len(gh_data)
        except Exception:
            hout["records"] = None
        history_stage["outputs"].append(hout)

        history_stage["stats"].update({
            "systems_total":  systems_total,
            "software_total": software_total,
            "entries_total":  entries_total,
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

    need_files = [
        Path("output/mame_machines.json"),
        Path("output/gh_ini_classifications.json"),
        Path("output/mame_parent_index.json"),
    ]
    missing_files = [p.as_posix() for p in need_files if not p.exists()]

    if ok_mame and ok_ini and not missing_files:
        ok_transform = run_transformer(Path("data"))
        transform_errs = []
    else:
        ok_transform = False
        transform_errs = []
        if not ok_ini:
            transform_errs.append("skipped: INI parsing failed")
        if not ok_mame:
            transform_errs.append("skipped: MAME parsing failed")
        for mf in missing_files:
            transform_errs.append(f"skipped: missing prerequisite file {mf}")

    transform_duration = round(time.perf_counter() - tr_t0, 3)
    transform_finished_utc = datetime.datetime.utcnow().isoformat() + "Z"

    transform_stage = {
        "stage": "transform",
        "ok": bool(ok_transform),
        "started_utc": transform_started_utc,
        "finished_utc": transform_finished_utc,
        "duration_seconds": transform_duration,
        "inputs": [],
        "outputs": [],
        "stats": {},
    }
    if transform_errs:
        transform_stage["errors"] = transform_errs

    for p in need_files:
        if p.exists():
            transform_stage["inputs"].append(_file_meta(p))

    ov_path = Path("data/title_overrides.json")
    if ov_path.exists():
        transform_stage["inputs"].append(_file_meta(ov_path))

    wiki_out_path = Path("output/exotica_lit_wiki.json")
    tr_summary_path = Path("data/transform_summary.json")

    if ok_transform:
        if wiki_out_path.exists():
            w = _file_meta(wiki_out_path)
            try:
                with open(wiki_out_path, encoding="utf-8") as f:
                    wiki_map = json.load(f)
                w["records"] = len(wiki_map) if isinstance(wiki_map, dict) else None
            except Exception:
                w["records"] = None
            transform_stage["outputs"].append(w)

        if tr_summary_path.exists():
            s = _file_meta(tr_summary_path)
            transform_stage["outputs"].append(s)
            try:
                with open(tr_summary_path, encoding="utf-8") as f:
                    ts = json.load(f)
                c = ts.get("counts", {})
                transform_stage["stats"].update({
                    "eligible_parents": c.get("eligible_parents"),
                    "final_included": c.get("final_included"),
                    "clones_included_unknown_classification": c.get("clones_included_unknown_classification"),
                })
            except Exception:
                pass

        raw_path = Path("output/exotica_lit_raw_data.json")
        if raw_path.exists():
            rmeta = _file_meta(raw_path)
            try:
                with open(raw_path, encoding="utf-8") as f:
                    raw_map = json.load(f)
                rmeta["records"] = len(raw_map) if isinstance(raw_map, dict) else None
            except Exception:
                rmeta["records"] = None
            transform_stage["outputs"].append(rmeta)

        redirects_path = Path("output/exotica_wiki_pages_and_redirects.json")
        if redirects_path.exists():
            rdmeta = _file_meta(redirects_path)
            try:
                with open(redirects_path, encoding="utf-8") as f:
                    redirects = json.load(f)
                rdmeta["records"] = len(redirects) if isinstance(redirects, list) else None
            except Exception:
                rdmeta["records"] = None
            transform_stage["outputs"].append(rdmeta)

    stage_fragments.append(transform_stage)

    # ---------------- Manifest ----------------
    started_candidates = [ini_stage.get("started_utc"),
                          mame_stage.get("started_utc"),
                          history_stage.get("started_utc"),
                          transform_stage.get("started_utc")]
    finished_candidates = [ini_stage.get("finished_utc"),
                           mame_stage.get("finished_utc"),
                           history_stage.get("finished_utc"),
                           transform_stage.get("finished_utc")]
    started_candidates  = [t for t in started_candidates  if t]
    finished_candidates = [t for t in finished_candidates if t]

    run_started  = min(started_candidates)  if started_candidates  else datetime.datetime.utcnow().isoformat() + "Z"
    run_finished = max(finished_candidates) if finished_candidates else datetime.datetime.utcnow().isoformat() + "Z"

    manifest = {
        "schema_version": 1,
        "run_id": datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        "started_utc": run_started,
        "finished_utc": run_finished,
        "stages": [ini_stage, mame_stage, history_stage, transform_stage],
    }

    Path("data").mkdir(parents=True, exist_ok=True)
    with open("data/run_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    log.info("Wrote data/run_manifest.json")


if __name__ == "__main__":
    main()
