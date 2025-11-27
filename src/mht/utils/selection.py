from __future__ import annotations

from typing import Dict, Any, Set, List, Tuple

from mht.utils.ini import is_not_available_label


__all__ = ["classify", "is_eligible_parent", "build_final_set"]

_UNKNOWN = "unknown"


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

def classify_from_ini(machine_name: str, parsed: Dict[str, dict]) -> Dict[str, object]:
    """
    Classify a machine using the parsed INI bundle produced by load_ini_classifications().

    Returns
    -------
    dict with keys:
      - game_status : "game" | "no_game" | "unknown"
      - category    : list[str] (never empty; "unknown" if none)
      - type        : str (single; "unknown" if none or '<not available>')
    """
    # Game status
    gs_set: Set[str] = (parsed.get("game_status", {}) or {}).get("machine_sections", {}).get(machine_name, set())
    if is_not_available_label(next(iter(gs_set), None)) and len(gs_set) == 1:
        game_status = _UNKNOWN
    elif "Game" in gs_set:
        game_status = "game"
    elif "No Game" in gs_set:
        game_status = "no_game"
    elif gs_set:
        game_status = _UNKNOWN
    else:
        game_status = _UNKNOWN

    # Category (array)
    cat_set: Set[str] = (parsed.get("category", {}) or {}).get("machine_sections", {}).get(machine_name, set()).copy()
    cat_labels = []
    for c in cat_set:
        cat_labels.append(_UNKNOWN if is_not_available_label(c) else c)
    if not cat_labels:
        cat_labels = [_UNKNOWN]
    if len(cat_labels) > 1 and _UNKNOWN in cat_labels:
        cat_labels = [c for c in cat_labels if c != _UNKNOWN]
    category_list = sorted(set(cat_labels))

    # Type (single)
    type_set: Set[str] = (parsed.get("type", {}) or {}).get("machine_sections", {}).get(machine_name, set())
    if not type_set:
        machine_type = _UNKNOWN
    elif any(is_not_available_label(t) for t in type_set):
        machine_type = _UNKNOWN
    else:
        machine_type = sorted(type_set)[0]

    return {"game_status": game_status, "category": category_list, "type": machine_type}

def inherit_parent_classification_for_clones(
    ini_map: Dict[str, Dict[str, Any]],
    parent_index: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """
    Return a new INI classification map where any clone machine inherits its
    parent's classification if:

      - the clone has no entry in ini_map, and
      - the parent *does* have an entry in ini_map.

    This is a transform-time convenience only. The on-disk gh_ini_classifications.json
    continues to reflect the raw INI contents (parents only in newer GH drops).
    """
    if not isinstance(ini_map, dict):
        return {}

    child_to_parent: Dict[str, str] = (parent_index or {}).get("child_to_parent", {}) or {}
    if not child_to_parent:
        # Nothing to inherit; return the original mapping unchanged.
        return dict(ini_map)

    expanded: Dict[str, Dict[str, Any]] = dict(ini_map)

    for clone_name, parent_name in child_to_parent.items():
        # Only inherit when:
        #  - the clone is not already classified
        #  - the parent has a classification row
        if clone_name in expanded:
            continue
        parent_row = ini_map.get(parent_name)
        if not isinstance(parent_row, dict):
            continue
        expanded[clone_name] = parent_row

    return expanded

def build_eligible_parents_set(mame: Dict[str, Dict[str, Any]], ini_map: Dict[str, Any]) -> Set[str]:
    """
    Return the set of parent machine names that are eligible according to INI classification.
    Mirrors the inline comprehension previously in the pipeline.
    """
    from mht.utils.selection import is_eligible_parent  # local reuse without circulars
    return {
        n
        for n, v in mame.items()
        if not (v or {}).get("cloneof") and is_eligible_parent(n, mame, ini_map)
    }

def universe_parent_clone_counts(mame: Dict[str, Dict[str, Any]]) -> Tuple[int, int]:
    """
    Compute total parents and total clones from the canonical mame_machines map.
    """
    parents_total = sum(1 for v in mame.values() if not (v or {}).get("cloneof"))
    clones_total  = sum(1 for v in mame.values() if (v or {}).get("cloneof"))
    return parents_total, clones_total
