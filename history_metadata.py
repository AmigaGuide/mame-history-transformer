from pathlib import Path
from collections import defaultdict
import json
import time

from config import LOG_LEVEL
from logger import setup_logger
from encoding_utils import load_or_create_encodings

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

def _load_ini_classifications():
    """
    Loads all classification .ini files into internal cache.
    Automatically detects encoding using the existing encodings.json logic.
    """
    global _ini_parsed
    if _ini_parsed:
        return

    start = time.perf_counter()
    encoding_paths = list(INI_FILES.values())
    encodings = load_or_create_encodings(encoding_paths)

    for key, path in INI_FILES.items():
        encoding = encodings.get(path.name, "utf-8")
        log.debug(f"Parsing {path.name} with encoding {encoding}...")
        _ini_data_cache[key] = _parse_ini_file(path, encoding)

    _ini_parsed = True
    duration = time.perf_counter() - start
    log.info(f"INI classification data loaded in {duration:.2f} seconds")

def classify_machine(machine_name: str) -> dict[str, str]:
    """
    Returns classification details for a MAME machine from the .ini metadata.

    Args:
        machine_name (str): MAME machine name.

    Returns:
        dict: {
            "game_status": "Game" | "No Game" | "<not available>",
            "category":    section label or "<not available>",
            "type":        section label or "<not available>"
        }
    """
    _load_ini_classifications()

    result = {}
    for key in ["game_status", "category", "type"]:
        value = _ini_data_cache[key].get(machine_name, "<not available>")
        result[key] = value

    return result

def is_valid_arcade_game(machine_name: str) -> bool:
    """
    Returns True if the machine is considered a valid arcade game,
    based on 'Game Or No Game' and 'Machine Category' .ini files.

    Args:
        machine_name (str): MAME machine name.

    Returns:
        bool: True if it passes both classification checks.
    """
    _load_ini_classifications()

    game_status = _ini_data_cache["game_status"].get(machine_name, "<not available>")
    category = _ini_data_cache["category"].get(machine_name, "<not available>")

    return game_status == "Game" and category in {"Arcade", "Coin-Op (Games)"}

def summarise_ini_classifications() -> dict[str, dict[str, int]]:
    """
    Produces a count of how many machines fall under each section for each .ini file.

    Returns:
        dict: Summary dictionary by ini type, e.g.
              { "game_status": {"Game": 10000, "No Game": 3000}, ... }
    """
    _load_ini_classifications()

    summary = {}
    for key in ["game_status", "category", "type"]:
        counts = defaultdict(int)
        for section in _ini_data_cache[key].values():
            counts[section] += 1
        summary[key] = dict(counts)
        log.debug(f"Classification summary for {key}: {dict(counts)}")

    return summary

def get_excluded_machine_preview(limit: int = 10) -> list[tuple[str, str, str]]:
    """
    Returns the first N machine names that would be excluded based on game status and category rules.

    Args:
        limit (int): Number of machines to return.

    Returns:
        list of tuples: [(machine_name, game_status, category), ...]
    """
    _load_ini_classifications()

    excluded = []
    all_machines = set().union(*[_ini_data_cache[k].keys() for k in _ini_data_cache])

    for machine in sorted(all_machines):
        if not is_valid_arcade_game(machine):
            result = classify_machine(machine)
            excluded.append((machine, result["game_status"], result["category"]))
            if len(excluded) >= limit:
                break

    return excluded
