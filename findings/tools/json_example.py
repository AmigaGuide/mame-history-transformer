"""
TM470 – JSON Example Builder (sidecar-data version, no port-cropping)

Sidecar files (must sit next to this script):
  - json_example_mame_data.json     (base per-game MAME data)
  - json_example_ports_data.json    (per-game PORTS; supports multiple shapes)
  - json_example_trivia_data.json   (cropped real trivia for 'puckman' only)

Outputs:
  - json_example_before_trivia.json          (header + ALL games, MAME + PORTS, NO trivia)
  - json_example_puckman_with_trivia.json    (header + puckman ONLY, MAME + PORTS + TRIVIA)
"""

from pathlib import Path
import json
import copy
from typing import Any, Dict, Optional

HERE = Path(__file__).parent

# ---- Sidecar inputs ----
MAME_DATA_FILE   = HERE / "json_example_mame_data.json"
PORTS_DATA_FILE  = HERE / "json_example_ports_data.json"
TRIVIA_DATA_FILE = HERE / "json_example_trivia_data.json"

# ---- Outputs ----
OUTPUT_BEFORE              = HERE / "json_example_before_trivia.json"
OUTPUT_PUCKMAN_WITH_TRIVIA = HERE / "json_example_puckman_with_trivia.json"

# ---- Header versions ----
HEADER_VERSIONS = {
    "mame_xml_version": "0.279",
    "gaming_history_xml_version": "0.279",
    "ini_versions": {
        "[GAMING HISTORY] Game Or No Game.ini": "0.279",
        "[GAMING HISTORY] Machine Category.ini": "0.279",
        "[GAMING HISTORY] Machine Type.ini": "0.279"
    }
}

# =========================
# Helpers
# =========================

def load_json(path: Path) -> Any:
    """Load JSON from path; return None if missing."""
    if not path.exists():
        print(f"[note] File not found, skipping: {path.name}")
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def write_json(path: Path, obj: dict) -> None:
    """Write pretty JSON to path."""
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=4)
    print(f"[ok] Wrote: {path.name}")

def ensure_games_map(mame_map: Any) -> Dict[str, Dict[str, Any]]:
    """Validate MAME data is an object keyed by game shortnames."""
    if not isinstance(mame_map, dict):
        raise SystemExit("json_example_mame_data.json must be a JSON object keyed by game shortnames.")
    for k, v in mame_map.items():
        if not isinstance(v, dict):
            raise SystemExit(f"MAME entry for '{k}' must be an object/dict.")
    return mame_map  # type: ignore[return-value]

def _normalise_ports_root(ports_data: Any) -> Optional[Dict[str, Any]]:
    """
    Accepts any of these shapes and returns a dict keyed by game:
      (A) { "puckman": { "CONSOLES": [...], ... }, "ninjaw": {...}, ... }
      (B) { "puckman": { "ports": { ... } }, "ninjaw": { "ports": { ... } }, ... }
      (C) { "games": { "puckman": { "ports": { ... } }, ... } }
    Returns None if ports_data is missing/invalid.
    """
    if not isinstance(ports_data, dict):
        return None
    if "games" in ports_data and isinstance(ports_data["games"], dict):
        return ports_data["games"]
    return ports_data  # already game-keyed

def _extract_ports_for_game(ports_root: Optional[Dict[str, Any]], game_key: str) -> Optional[Dict[str, Any]]:
    """
    From the normalised ports_root, return the PORTS dict for a single game, handling:
      - game -> { "ports": { ... } }
      - game -> { "CONSOLES": [...], "COMPUTERS": [...], ... }
    """
    if not ports_root:
        return None
    val = ports_root.get(game_key)
    if not isinstance(val, dict):
        return None
    # Looks like a ports dict already?
    if any(k in val for k in ("CONSOLES", "HANDHELDS", "COMPUTERS", "OTHERS")):
        return val
    # Or wrapped under "ports"
    maybe = val.get("ports")
    if isinstance(maybe, dict):
        return maybe
    return None

def extract_puckman_trivia(trivia_data: Any) -> Optional[Any]:
    """Accept either a list or a dict with key 'puckman' mapping to a list."""
    if trivia_data is None:
        return None
    if isinstance(trivia_data, list):
        return trivia_data
    if isinstance(trivia_data, dict):
        val = trivia_data.get("puckman")
        if isinstance(val, list):
            return val
    return None

def attach_ports_to_all(games: Dict[str, Dict[str, Any]], ports_data: Any) -> None:
    """Attach PORTS to each game in-place, handling multiple ports file shapes."""
    ports_root = _normalise_ports_root(ports_data)
    if not ports_root:
        print("[note] No usable ports data found; skipping ports for all games.")
        return

    for game_key, game in games.items():
        ports_for_game = _extract_ports_for_game(ports_root, game_key)
        if ports_for_game:
            game["ports"] = ports_for_game
            # Debug line to confirm categories found:
            print(f"[ok] Attached ports for {game_key} (categories: {', '.join(ports_for_game.keys())})")
        else:
            print(f"[note] No ports found for {game_key}")

def build_full_puckman(mame_map: Dict[str, Dict[str, Any]], ports_data: Any, trivia_data: Any) -> Dict[str, Any]:
    """Merge base MAME + PORTS + TRIVIA for 'puckman' only."""
    puck = copy.deepcopy(mame_map.get("puckman", {}))
    if not puck:
        raise SystemExit("No 'puckman' entry found in json_example_mame_data.json.")

    ports_root = _normalise_ports_root(ports_data)
    puck_ports = _extract_ports_for_game(ports_root, "puckman")
    if puck_ports:
        puck["ports"] = puck_ports

    puck_trivia = extract_puckman_trivia(trivia_data)
    if puck_trivia is not None:
        puck["trivia"] = puck_trivia

    return puck

# =========================
# Main
# =========================

def main():
    # 1) Load sidecar datasets
    mame_data   = load_json(MAME_DATA_FILE)
    ports_data  = load_json(PORTS_DATA_FILE)    # may be None
    trivia_data = load_json(TRIVIA_DATA_FILE)   # may be None

    # 2) Validate and copy MAME base
    games = ensure_games_map(mame_data)
    games = copy.deepcopy(games)  # keep originals untouched

    # 3) Attach ports to ALL games for the before-trivia file
    attach_ports_to_all(games, ports_data)

    # 4) Emit BEFORE-TRIVIA (all games, MAME + PORTS, no trivia)
    before_payload = {
        "header": {"versions": HEADER_VERSIONS},
        "games": games,
        "notes": "Structure-only mock; trivia intentionally excluded."
    }
    write_json(OUTPUT_BEFORE, before_payload)

    # 5) Build PUCKMAN-ONLY (MAME + PORTS + TRIVIA) and emit
    full_puckman = build_full_puckman(mame_map=mame_data, ports_data=ports_data, trivia_data=trivia_data)
    puckman_only_payload = {
        "header": {"versions": HEADER_VERSIONS},
        "games": {"puckman": full_puckman}
    }
    write_json(OUTPUT_PUCKMAN_WITH_TRIVIA, puckman_only_payload)

    print("[done] Generated both example files successfully.")

if __name__ == "__main__":
    main()
