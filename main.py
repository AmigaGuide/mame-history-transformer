"""
Filename: main.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Entry point for the XML parsing and classification pipeline. Validates the presence
of required source files, detects encodings, verifies version consistency, logs 
classification summaries, and initiates parsing of the MAME XML dataset.

The output is a clone-aware, classification-filtered list of valid arcade machines
from the MAME XML, suitable for transformation into wiki-compatible JSON.

This file is part of a student project and is not intended for commercial use.
"""

import json
import re
import time
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET
import hashlib

from config import LOG_LEVEL
from logger import setup_logger, debug_log
from encoding_utils import detect_encoding
from mame_parser import parse_mame_xml
from history_parser import parse_history_entries
from history_metadata import parse_history_inis
from transformer import run_transformer


log = setup_logger(log_level=LOG_LEVEL)
ENCODINGS_PATH = Path("data/encodings.json")
ok_mame = False
ok_history = False


# Version parsing helpers (suffix-tolerant: e.g., '2.79a', '0.279-rc1')
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


def _history_root_attrs(p: Path, encoding: str = "utf-8") -> dict:
    """
    Read the root element of history.xml and return {'history_version','history_date'} if present.
    """
    try:
        # This reads only as much as needed to parse the root
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
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def _file_meta(p: Path) -> dict:
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
        s (str): Raw version string, e.g. '0.279', '2.79a', '0.279-rc1'.

    Returns:
        Tuple[Tuple[int, ...], Optional[str]]: (numeric_core_tuple, suffix_or_None).
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
    Convert a numeric core tuple into a dotted string.

    Args:
        core (Tuple[int, ...]): e.g. (0, 279)

    Returns:
        Optional[str]: dotted representation, e.g. '0.279', or None if empty.
    """
    if not core:
        return None
    return ".".join(str(n) for n in core)


def same_numeric_core(*version_strings: str) -> bool:
    """
    Check whether all provided version strings share the same numeric core.

    Args:
        *version_strings (str): One or more version strings.

    Returns:
        bool: True if all numeric cores match (ignoring suffixes) and none are unparsable.
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
    Create a structured record for a version string capturing raw, numeric_core, and suffix.

    Args:
        raw (str): Raw version string as read from file.

    Returns:
        Dict[str, Optional[str]]: {'raw', 'numeric_core', 'suffix'}.
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
    Check for the presence of required XML and INI files in the 'data' folder.
    If any are missing, print download instructions.

    Returns:
        Optional[List[Path]]: List of required file paths, or None if missing.
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
    Extract version or build info from the root tag of an XML file.

    Args:
        file_path (Path): Path to the XML file.
        root_tag (str): Expected root tag name ('mame' or 'history').

    Returns:
        str: Raw version or build string, or 'Unknown'/'Parse Error' on failure.
    """
    try:
        for event, elem in ET.iterparse(file_path, events=("start",)):
            if elem.tag == root_tag:
                # MAME typically uses 'build'; History uses 'version'
                return elem.attrib.get("build") or elem.attrib.get("version", "Unknown")
    except ET.ParseError:
        log.error(f"Parse error reading {file_path}")
        return "Parse Error"
    return "Unknown"


def get_ini_version(file_path: Path, encoding: str) -> str:
    """
    Extract a version string from the top of a .ini file.
    Accepts suffixes (e.g., '2.79a') as part of the captured version.

    Args:
        file_path (Path): Path to the INI file.
        encoding (str): Text encoding to use for reading.

    Returns:
        str: Raw version string, or 'Unknown' if not found.
    """
    try:
        with open(file_path, encoding=encoding) as f:
            for line in f:
                if line.strip().startswith(";;") and "MAME" in line:
                    # Example line: ";; MAME 0.279a ...", capture the version token after 'MAME '
                    match = re.search(r"MAME\s+([0-9]+\.[0-9A-Za-z._-]+)", line)
                    if match:
                        return match.group(1)
    except Exception as e:
        log.warning(f"Could not extract version from {file_path.name}: {e}")
    return "Unknown"


# ---------------------------------------------------------------------------
# (Legacy) Normalisation helper - kept for compatibility, not used now
# ---------------------------------------------------------------------------

def normalise_version(version_str: str) -> str:
    """
    Legacy normaliser retained for compatibility. Prefer parse_version_loose().
    Attempts to reshape to '0.XXX' but does not understand suffixes.

    Args:
        version_str (str): Raw version.

    Returns:
        str: '0.xxx' style or 'Unknown' if not convertible.
    """
    version_str = (version_str or "").strip()
    version_str = re.sub(r"\s*\(.*?\)", "", version_str)

    if version_str.startswith("0."):
        return version_str

    try:
        version_float = float(version_str)
        return f"{version_float / 10:.3f}"
    except ValueError:
        log.warning(f"Could not normalise version string (legacy path): {version_str}")
        return "Unknown"


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    """
    Orchestrate presence checks, encoding detection, version comparison (suffix-tolerant),
    cache persistence, and the invocation of MAME and History parsers.
    """
    log.info("Starting TM470 XML parsing pipeline...")

    required_paths = check_required_files()
    if not required_paths:
        log.error("Aborting. Required files missing.")
        return

    data_dir = Path("data")
    encoding_cache: Dict[str, Dict[str, Any]] = {}

    # Load existing encodings.json if it exists (backwards-compatible with old shape)
    if ENCODINGS_PATH.exists():
        try:
            with open(ENCODINGS_PATH, "r", encoding="utf-8") as f:
                encoding_cache = json.load(f)
            log.info("Loaded encoding cache from encodings.json")
        except (json.JSONDecodeError, IOError):
            log.warning("Could not read encodings.json. Will re-parse all files.")
            encoding_cache = {}

    updated_encodings: Dict[str, Dict[str, Any]] = {}

    # Pass 1: gather current raw versions (using either cached encoding or fresh detection)
    for file_path in required_paths:
        fname = file_path.name
        stored_entry = encoding_cache.get(fname) or {}
        stored_enc = stored_entry.get("encoding")

        # Determine encoding (use cached if available; else detect)
        if stored_enc:
            encoding = stored_enc
        else:
            encoding = detect_encoding(file_path)

        # Extract a raw version string using the chosen encoding (for INIs) or via XML root
        if fname.endswith(".xml"):
            root_tag = "mame" if "mame" in fname.lower() else "history"
            raw_version = get_xml_version(file_path, root_tag)
        elif fname.endswith(".ini"):
            raw_version = get_ini_version(file_path, encoding)
        else:
            raw_version = "Unknown"

        # Build a structured version record
        vrec = version_record(raw_version)

        # Decide whether to reuse cached encoding or replace it (we keep the detected one for safety)
        updated_encodings[fname] = {
            "encoding": encoding,
            "version": vrec  # {'raw', 'numeric_core', 'suffix'}
        }

    # Save encodings/versions (structured) to cache
    with open(ENCODINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(updated_encodings, f, indent=4)
    log.info("Saved updated encodings.json")

    # ------------------------------
    # Version consistency reporting
    # ------------------------------
    # Read the set back (to be explicit) and compute cross-file comparison.
    mame_ver_raw = updated_encodings.get("mame.xml", {}).get("version", {}).get("raw", "Unknown")
    hist_ver_raw = updated_encodings.get("history.xml", {}).get("version", {}).get("raw", "Unknown")
    ini_game_raw = updated_encodings.get("[GAMING HISTORY] Game Or No Game.ini", {}).get("version", {}).get("raw", "Unknown")
    ini_cat_raw  = updated_encodings.get("[GAMING HISTORY] Machine Category.ini", {}).get("version", {}).get("raw", "Unknown")
    ini_type_raw = updated_encodings.get("[GAMING HISTORY] Machine Type.ini", {}).get("version", {}).get("raw", "Unknown")

    all_versions = [mame_ver_raw, hist_ver_raw, ini_game_raw, ini_cat_raw, ini_type_raw]
    if not same_numeric_core(*all_versions):
        log.warning("Version mismatch (numeric core differs): %s", ", ".join(v for v in all_versions if v))
    else:
        # Surface any suffixes (non-blocking, informative)
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

    # Pass encodings to downstream modules (simple map: filename -> encoding string)
    encodings = {k: v["encoding"] for k, v in updated_encodings.items() if isinstance(v, dict) and "encoding" in v}

    log.info("Beginning History .ini parse...")
    ini_started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    ini_t0 = time.perf_counter()

    ok_ini = parse_history_inis(data_dir, encodings)

    ini_duration = round(time.perf_counter() - ini_t0, 3)
    ini_finished_utc = datetime.datetime.utcnow().isoformat() + "Z"

    # Build manifest stage (index + pointers; no duplication of detailed stats)
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

    ini_outputs = []
    ini_stats = {}
    # Attach output metadata if present
    if ini_summary_path.exists():
        meta = _file_meta(ini_summary_path)
        ini_outputs.append(meta)
        # Pull a small headline stat from the summary (optional, not duplicative)
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
        # Add record count = number of machines in the classification map
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


    # --- MAME parse (timed) ---
    log.info("Beginning MAME XML canonical parse...")
    mame_started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    mame_t0 = time.perf_counter()
    ok_mame = parse_mame_xml(data_dir / "mame.xml", encodings=encodings, max_records=0)
    mame_duration = round(time.perf_counter() - mame_t0, 3)
    mame_finished_utc = datetime.datetime.utcnow().isoformat() + "Z"
    # --- MAME stage fragment ---
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

        # output meta + record count
        mout = _file_meta(mame_out_path)
        mout["summary_path"] = mame_summary_path.as_posix()
        with open(mame_out_path, encoding="utf-8") as f:
            m_machines = json.load(f)
        mout["records"]     = len(m_machines)
        mame_stage["outputs"].append(mout)

        # ALSO include parent/clone index if present
        mame_parent_idx_path = Path("output/mame_parent_index.json")
        if mame_parent_idx_path.exists():
            mp = _file_meta(mame_parent_idx_path)
            try:
                with open(mame_parent_idx_path, encoding="utf-8") as f:
                    idx = json.load(f)
                # records: number of parents-with-clones
                mp["records"] = len(idx.get("parents", {})) if isinstance(idx, dict) else None
            except Exception:
                mp["records"] = None
            mame_stage["outputs"].append(mp)

        # headline counters
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


    # --- HISTORY parse (timed) ---
    log.info("Beginning History XML parse...")
    history_started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    hist_t0 = time.perf_counter()
    # --- HISTORY stage fragment ---
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

        # version info on the input
        hx = _history_root_attrs(history_xml, encoding=encodings.get("history.xml", "utf-8"))
        history_stage["inputs"][0]["version"] = {k: v for k, v in hx.items() if v}

        # output meta + record count (from file)
        hout = _file_meta(gh_out_path)
        hout["summary_path"] = hist_summary_path.as_posix()
        try:
            with open(gh_out_path, encoding="utf-8") as f:
                gh_data = json.load(f)         # dict
            hout["records"] = len(gh_data)
        except Exception:
            hout["records"] = None
        history_stage["outputs"].append(hout)

        # keep totals in stats
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



    # --- TRANSFORM (timed) ---
    log.info("Beginning transform (no Ports yet)...")
    transform_started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    tr_t0 = time.perf_counter()

    # prerequisites: INI + MAME must have succeeded, and required files must exist
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

    # attach input file meta (for traceability) if present
    for p in need_files:
        if p.exists():
            transform_stage["inputs"].append(_file_meta(p))

    # Optionally record the title overrides file as an input (not a prerequisite)
    ov_path = Path("data/title_overrides.json")
    if ov_path.exists():
        transform_stage["inputs"].append(_file_meta(ov_path))

    # attach outputs + light stats if transform ran
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
            # Pull a couple of headline stats (optional, compact)
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

    stage_fragments.append(transform_stage)


    started_candidates = [ini_stage.get("started_utc"),
                          mame_stage.get("started_utc"),
                          history_stage.get("started_utc"),
                          transform_stage.get("started_utc")]

    finished_candidates = [ini_stage.get("finished_utc"),
                           mame_stage.get("finished_utc"),
                           history_stage.get("finished_utc"),
                           transform_stage.get("finished_utc")]


    # Filter out any None
    started_candidates  = [t for t in started_candidates  if t]
    finished_candidates = [t for t in finished_candidates if t]

    run_started  = min(started_candidates)  if started_candidates  else datetime.datetime.utcnow().isoformat() + "Z"
    run_finished = max(finished_candidates) if finished_candidates else datetime.datetime.utcnow().isoformat() + "Z"


    manifest = {
        "schema_version": 1,
        "run_id": datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        "started_utc": run_started,
        "finished_utc": run_finished,
        "stages": [ini_stage, mame_stage, history_stage],
    }


    Path("data").mkdir(parents=True, exist_ok=True)
    with open("data/run_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    log.info("Wrote data/run_manifest.json")


if __name__ == "__main__":
    main()
