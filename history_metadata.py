from pathlib import Path
import json

# Paths
ini_dir = Path("data")
encodings_path = ini_dir / "encodings.json"

# INI files to process
ini_files = {
    "game_status": "[GAMING HISTORY] Game Or No Game.ini",
    "category": "[GAMING HISTORY] Machine Category.ini",
    "type": "[GAMING HISTORY] Machine Type.ini"
}

_ini_data_cache = None


def _load_encoding(file_name: str) -> str:
    """
    Loads the encoding for a given file from encodings.json.
    Falls back to 'utf-8' if not found (though this should not occur if main.py ran).
    """
    try:
        with open(encodings_path, encoding="utf-8") as f:
            encodings = json.load(f)
        return encodings.get(file_name, "utf-8")
    except (FileNotFoundError, json.JSONDecodeError):
        return "utf-8"


def _load_custom_ini_file(filepath: Path, label: str) -> dict:
    """
    Parses a Gaming-History .ini file using its detected encoding.
    Skips comments and [FOLDER_SETTINGS].
    """
    data = {}
    current_section = None
    encoding = _load_encoding(filepath.name)

    with open(filepath, encoding=encoding) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";;"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1]
                continue
            if current_section == "FOLDER_SETTINGS":
                continue
            machine_name = line
            if machine_name:
                data.setdefault(machine_name, {})[label] = current_section
    return data


def _load_all_ini_data() -> dict:
    """
    Loads and merges all .ini metadata into a single dictionary keyed by machine name.
    """
    combined = {}
    for label, filename in ini_files.items():
        path = ini_dir / filename
        parsed = _load_custom_ini_file(path, label)
        for machine, values in parsed.items():
            combined.setdefault(machine, {}).update(values)
    return combined


def classify_machine(machine_name: str) -> dict:
    """
    Returns classification metadata for a given MAME machine name.

    Returns:
        dict: e.g. { 'game_status': 'Game', 'category': 'Arcade', 'type': 'Arcade Video game' }
              or empty {} if not found.
    """
    global _ini_data_cache
    if _ini_data_cache is None:
        _ini_data_cache = _load_all_ini_data()
    return _ini_data_cache.get(machine_name, {})
