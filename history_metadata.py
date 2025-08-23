"""
Filename: history_metadata.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Parses and caches classification metadata from three Gaming-History .ini files:
- Game Or No Game.ini
- Machine Category.ini
- Machine Type.ini

Provides functions to determine whether a MAME machine is a valid arcade game,
summarise classifications, and retrieve detailed metadata for use in downstream
processing and final data exports.

This file is part of a student project and is not intended for commercial use.
"""

from pathlib import Path
from collections import defaultdict
import time
import hashlib, datetime
import re, datetime

from config import LOG_LEVEL
from logger import setup_logger, debug_log

log = setup_logger(log_level=LOG_LEVEL)

# Paths to .ini files
DATA_DIR = Path("data")
INI_FILES = {
    "game_status": DATA_DIR / "[GAMING HISTORY] Game Or No Game.ini",
    "category": DATA_DIR / "[GAMING HISTORY] Machine Category.ini",
    "type": DATA_DIR / "[GAMING HISTORY] Machine Type.ini"
}

_ini_data_cache = {
    "game_status": {},
    "category": {},
    "type": {}
}

_ini_parsed = False


def _to_iso_date(s: str) -> str | None:
    # "08/08/2025" -> "2025-08-08"
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            pass
    return None


def _ini_version_info(p: Path, encoding: str = "utf-8") -> dict:
    """
    Extract MAME version/build and generated date from the INI header region.
    Works even if the header formatting varies.
    """
    try:
        with open(p, "r", encoding=encoding, errors="replace") as f:
            head = f.read(16384)  # first 16 KB is plenty
    except Exception:
        return {}

    # Normalise: strip BOM, collapse whitespace
    head = head.lstrip("\ufeff")
    head = re.sub(r"\s+", " ", head)

    info: dict[str, str] = {}

    # 1) Grab MAME version/build anywhere near the top
    mv = re.search(r"(?i)\bMAME\s+([0-9.]+)\b", head)
    mb = re.search(r"(?i)\((mame[0-9]+)\)", head)
    if mv:
        info["mame_version"] = mv.group(1)
    if mb:
        info["mame_build"] = mb.group(1).lower()

    # 2) Find a generated/updated date (accept dd/mm/yyyy or yyyy-mm-dd)
    dt = re.search(
        r"(?i)(?:generated|updated)\s*(?:@|on|:)?\s*([0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})",
        head,
    )
    if dt:
        raw = dt.group(1)
        info["generated_date_raw"] = raw
        iso = _to_iso_date(raw)
        if iso:
            info["generated_date"] = iso

    return info


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

def _ini_line_counts(p: Path, encoding: str = "utf-8") -> tuple[int, int]:
    """
    Return (lines, non_comment_lines). Treat ';;' as the comment prefix
    to match GH INI style (we ignore blank lines).
    """
    lines = non_comment = 0
    with open(p, encoding=encoding) as f:
        for line in f:
            lines += 1
            s = line.strip()
            if s and not s.startswith(";;"):
                non_comment += 1
    return lines, non_comment


def summarise_history_inis(data_dir: Path, encodings: dict[str, str]) -> dict:
    """
    Summarise the three GH INIs so main.py can record them in run_manifest.json.

    Returns a 'stage fragment':
      {
        "stage": "history_metadata",
        "ok": True/False,
        "started_utc": "...", "finished_utc": "...", "duration_seconds": 0.0,
        "inputs": [ {path, size_bytes, modified_utc, sha256, lines, non_comment_lines, entries_indexed}, ... ],
        "outputs": [],   # INIs don’t produce standalone outputs
        "stats": { "classification_counts": {...}, "unique_machine_names_indexed": N },
        "errors": [ ... ]
      }
    """
    started = time.perf_counter()
    started_utc = datetime.datetime.utcnow().isoformat() + "Z"

    inputs, errors = [], []

    # Ensure cache is loaded so we can report entries per INI
    _load_ini_classifications(encodings)

    # Per-INI metadata + counts
    for key, path in INI_FILES.items():
        try:
            if not path.exists():
                errors.append(f"Missing INI: {path.name}")
                continue
            meta = _file_meta(path)
            enc = encodings.get(path.name, "utf-8")
            total, non_comment = _ini_line_counts(path, encoding=enc)
            meta["lines"] = total
            meta["non_comment_lines"] = non_comment
            meta["entries_indexed"] = len(_ini_data_cache.get(key, {}))  # how many machine names mapped
            meta["version"] = _ini_version_info(path, encoding=enc)
            
            v = meta["version"]
            if not v:
                debug_log(f"No INI version parsed from header of {path.name}")

            inputs.append(meta)
        except Exception as e:
            errors.append(f"{path.name}: {e}")

    # Classification section counts you already support
    class_counts = summarise_ini_classifications(encodings)  # {game_status:{...}, category:{...}, type:{...}}

    # Union of all machine names across the three INIs (useful sanity number)
    all_names = set().union(*(_ini_data_cache[k].keys() for k in _ini_data_cache))

    ok = len(errors) == 0 and len(inputs) == len(INI_FILES)
    finished_utc = datetime.datetime.utcnow().isoformat() + "Z"
    duration = time.perf_counter() - started

    log.info(f"INI summary: {len(inputs)} files processed; ok={ok}; errors={len(errors)}")

    return {
        "stage": "history_metadata",
        "ok": ok,
        "started_utc": started_utc,
        "finished_utc": finished_utc,
        "duration_seconds": round(duration, 3),
        "inputs": inputs,
        "outputs": [],
        "stats": {
            "classification_counts": class_counts,
            "unique_machine_names_indexed": len(all_names),
        },
        "errors": errors,
    }




def _parse_ini_file(path: Path, encoding: str) -> dict[str, str]:
    """
    Parses an INI-style file where each [section] is followed by machine names.

    Args:
        path (Path): Path to the .ini file.
        encoding (str): File encoding.

    Returns:
        dict: Mapping of machine_name -> section label.
    """
    current_section = None
    mapping = {}

    with open(path, encoding=encoding) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";;"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1]
                continue
            if current_section and current_section != "FOLDER_SETTINGS":
                mapping[line] = current_section

    return mapping

def _load_ini_classifications(encodings: dict[str, str]):
    """
    Loads all classification .ini files into internal cache using provided encodings.

    Args:
        encodings (dict): Mapping of filename -> encoding, passed from main.py
    """
    global _ini_parsed
    if _ini_parsed:
        return

    start = time.perf_counter()

    for key, path in INI_FILES.items():
        encoding = encodings[path.name]
        debug_log(f"Parsing {path.name} with encoding {encoding}...")
        _ini_data_cache[key] = _parse_ini_file(path, encoding)

    _ini_parsed = True
    duration = time.perf_counter() - start
    log.info(f"INI classification data loaded in {duration:.2f} seconds")

def classify_machine(machine_name: str, encodings: dict[str, str]) -> dict[str, str]:
    """
    Returns classification details for a MAME machine from the .ini metadata.

    Args:
        machine_name (str): MAME machine name.
        encodings (dict): Encoding dictionary from main.py

    Returns:
        dict: {
            "game_status": "Game" | "No Game" | "<not available>",
            "category":    section label or "<not available>",
            "type":        section label or "<not available>"
        }
    """
    _load_ini_classifications(encodings)

    result = {}
    for key in ["game_status", "category", "type"]:
        value = _ini_data_cache[key].get(machine_name, "<not available>")
        result[key] = value

    return result

def is_valid_arcade_game(machine_name: str, encodings: dict[str, str]) -> bool:
    """
    Returns True if the machine is considered a valid arcade game,
    based on 'Game Or No Game' and 'Machine Category' .ini files.

    Args:
        machine_name (str): MAME machine name.
        encodings (dict): Encoding dictionary from main.py

    Returns:
        bool: True if it passes both classification checks.
    """
    _load_ini_classifications(encodings)

    game_status = _ini_data_cache["game_status"].get(machine_name, "<not available>")
    category = _ini_data_cache["category"].get(machine_name, "<not available>")

    return game_status == "Game" and category in {"Arcade", "Coin-Op (Games)"}

def summarise_ini_classifications(encodings: dict[str, str]) -> dict[str, dict[str, int]]:
    """
    Produces a count of how many machines fall under each section for each .ini file.

    Args:
        encodings (dict): Encoding dictionary from main.py

    Returns:
        dict: Summary dictionary by ini type, e.g.
              { "game_status": {"Game": 10000, "No Game": 3000}, ... }
    """
    _load_ini_classifications(encodings)

    summary = {}
    for key in ["game_status", "category", "type"]:
        counts = defaultdict(int)
        for section in _ini_data_cache[key].values():
            counts[section] += 1
        summary[key] = dict(counts)

        log.info(f"--- {key} ---")
        for label, count in sorted(counts.items()):
            debug_log(f"    {label}: {count}")

    return summary

def get_excluded_machine_preview(encodings: dict[str, str], limit: int = 10) -> list[tuple[str, str, str]]:
    """
    Returns the first N machine names that would be excluded based on game status and category rules.

    Args:
        encodings (dict): Encoding dictionary from main.py
        limit (int): Number of machines to return.

    Returns:
        list of tuples: [(machine_name, game_status, category), ...]
    """
    _load_ini_classifications(encodings)

    excluded = []
    all_machines = set().union(*[_ini_data_cache[k].keys() for k in _ini_data_cache])

    for machine in sorted(all_machines):
        if not is_valid_arcade_game(machine, encodings):
            result = classify_machine(machine, encodings)
            excluded.append((machine, result["game_status"], result["category"]))
            if len(excluded) >= limit:
                break

    return excluded
