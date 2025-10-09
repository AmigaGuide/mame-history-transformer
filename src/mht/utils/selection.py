from __future__ import annotations
from typing import Dict, Any, Set, List, Tuple


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

def build_parent_index(machines: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Build a minimal parent/clone index from the parsed MAME machines.

    Input:
        machines: { machine_name: { "cloneof": <str|""|None>, ... }, ... }

    Returns:
        {
          "parents": { parent_name: [clone_name_1, ...], ... },  # clones sorted, parents sorted
          "child_to_parent": { clone_name: parent_name, ... }    # keys sorted
        }

    Notes:
    - Behaviour mirrors the original _build_parent_index in mame_parser.py:
      * ignores entries without a 'cloneof' value
      * de-duplicates clone lists
      * sorts clone lists and then sorts the parent keys
      * sorts child_to_parent keys
    """
    parents: Dict[str, List[str]] = {}
    child_to_parent: Dict[str, str] = {}

    for mname, info in machines.items():
        parent = info.get("cloneof")
        if not parent:
            continue
        child_to_parent[mname] = parent
        parents.setdefault(parent, []).append(mname)

    parents_sorted: Dict[str, List[str]] = {
        p: sorted(set(clones)) for p, clones in parents.items() if clones
    }
    parents_sorted = {p: parents_sorted[p] for p in sorted(parents_sorted.keys())}
    child_to_parent_sorted = {c: child_to_parent[c] for c in sorted(child_to_parent.keys())}
    return {"parents": parents_sorted, "child_to_parent": child_to_parent_sorted}
