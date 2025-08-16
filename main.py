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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

from config import LOG_LEVEL
from logger import setup_logger, debug_log
from encoding_utils import detect_encoding
from mame_parser import parse_mame_xml
from history_parser import parse_history_entries


log = setup_logger(log_level=LOG_LEVEL)

ENCODINGS_PATH = Path("data/encodings.json")

# ---------------------------------------------------------------------------
# Version parsing helpers (suffix-tolerant: e.g., '2.79a', '0.279-rc1')
# ---------------------------------------------------------------------------

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

    log.info("Proceeding to XML parsing...")

    # Pass encodings to downstream modules (simple map: filename -> encoding string)
    encodings = {k: v["encoding"] for k, v in updated_encodings.items() if isinstance(v, dict) and "encoding" in v}

    # MAME XML parsing (clone-aware filtering performed within parse_mame_xml)
    log.info("Beginning MAME XML parsing...")
    machines = parse_mame_xml(data_dir / "mame.xml", encodings=encodings, max_records=0)
    log.info(f"Final machine count after clone-aware filtering: {len(machines)}")

    # History XML parsing
    log.info("Beginning History XML parsing...")
    gh_entries = parse_history_entries(data_dir / "history.xml", encodings.get("history.xml", "utf-8"))
    debug_log(f"Parsed GH entries count: {len(gh_entries) if gh_entries else 0}")


if __name__ == "__main__":
    main()
