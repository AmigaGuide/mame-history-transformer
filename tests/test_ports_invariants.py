import json


def _has_rows_in_categories(cat_map: dict) -> bool:
    # cat_map is a dict[str, list] like {"ARCADE": [...], "COMPUTER": [...]}
    # Any category with a non-empty list counts as having rows.
    if not isinstance(cat_map, dict):
        return False
    for v in cat_map.values():
        if isinstance(v, list) and len(v) > 0:
            return True
    return False

def _parent_has_rows(ports: dict) -> bool:
    ps = ports.get("parent_source") or {}
    cats = ps.get("categories") or {}
    return _has_rows_in_categories(cats)

def _clones_have_rows(ports: dict) -> bool:
    clones = ports.get("clone_sources") or []
    for c in clones:
        cats = (c or {}).get("categories") or {}
        if _has_rows_in_categories(cats):
            return True
    return False

def test_ports_shape_and_min_content(outputs_dir):
    RAW = (outputs_dir / "exotica_lit_raw_data.json")
    data = json.loads(RAW.read_text(encoding="utf-8"))

    # You only write games that have a Ports section
    games = data.get("games") or {}
    assert isinstance(games, dict)
    assert len(games) > 0

    for name, rec in games.items():
        ports = rec.get("ports")
        assert isinstance(ports, dict), f"{name}: missing ports"

        # Fixed shape: both keys must exist
        assert "parent_source" in ports, f"{name}: missing parent_source"
        assert "clone_sources" in ports, f"{name}: missing clone_sources"
        assert isinstance(ports["clone_sources"], list), f"{name}: clone_sources must be a list"

        # New rule: at least one side must have ≥1 PORT row
        parent_ok = _parent_has_rows(ports)
        clones_ok = _clones_have_rows(ports)
        assert parent_ok or clones_ok, f"{name}: neither parent nor clones contain PORT rows"
