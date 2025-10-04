from __future__ import annotations
from typing import Dict, Any, Set

__all__ = ["classify", "is_eligible_parent", "build_final_set"]


def classify(machine: str, ini_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Resolve a machine's INI-based classification.

    Returns a dict with keys:
      - game_status: "game" | "no_game" | "unknown"
      - category:    list[str] (non-empty; defaults to ["unknown"])
      - type:        str (defaults to "unknown")
    """
    row = (ini_map or {}).get(machine)
    if not row:
        return {"game_status": "unknown", "category": ["unknown"], "type": "unknown"}

    gs = (row.get("game_status") or "unknown") if isinstance(row, dict) else "unknown"

    cat = row.get("category") if isinstance(row, dict) else None
    if not isinstance(cat, list) or not cat:
        cat = ["unknown"]

    typ = (row.get("type") or "unknown") if isinstance(row, dict) else "unknown"

    return {"game_status": gs, "category": cat, "type": typ}


def is_eligible_parent(machine: str,
                       mame: Dict[str, Any],
                       ini_map: Dict[str, Dict[str, Any]]) -> bool:
    """
    Parent selection rule used by the transform stage:
      - must be a parent (no 'cloneof' in MAME record)
      - INI classification must be game_status == 'game'
      - INI categories must include 'Arcade'
    """
    info = (mame or {}).get(machine, {})
    if info.get("cloneof"):
        return False

    c = classify(machine, ini_map)
    return (c["game_status"] == "game") and ("Arcade" in c["category"])


def build_final_set(eligible_parents: Set[str],
                    parent_index: Dict[str, Any]) -> Set[str]:
    """
    Expand the selected parent set with their clones using the parent index.

    Returns the union of parents and their direct clones.
    """
    final: Set[str] = set(eligible_parents or set())
    parents_map: Dict[str, list] = (parent_index or {}).get("parents", {}) or {}

    for p in sorted(eligible_parents or []):
        final.update(parents_map.get(p, []) or [])

    return final
