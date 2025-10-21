from pathlib import Path
import json
from datetime import datetime, timezone
import pytest

# ---- helpers ----

def _is_iso8601_z(s: str) -> bool:
    try:
        if not isinstance(s, str) or not s.endswith("Z"):
            return False
        datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        return True
    except Exception:
        return False

@pytest.fixture(scope="module")
def _load(summaries_dir, read_json):
    """
    Bound loader for per-release summaries:
    data/releases/<ver>/summaries/<fname>
    """
    def _loader(fname: str):
        p = summaries_dir / fname
        if not p.exists():
            pytest.skip(f"missing: {p.as_posix()}")
        return read_json(p)
    return _loader

# ---------- MAME invariants ----------

def test_mame_totals_and_sums(_load):
    doc = _load("mame_parsing_summary.json")
    totals = doc.get("totals") or {}

    tm = totals.get("total_machines")
    tp = totals.get("total_parents")
    tc = totals.get("total_clones")
    assert isinstance(tm, int) and isinstance(tp, int) and isinstance(tc, int)
    assert tp + tc == tm

    for key, block in totals.items():
        if isinstance(block, dict) and "distribution" in block and "sum" in block:
            dist = block["distribution"]
            blk_sum = block["sum"]
            assert isinstance(dist, dict)
            assert sum(dist.values()) == blk_sum

def test_mame_dropped_displays_count_present_and_non_negative(_load):
    doc = _load("mame_parsing_summary.json")
    count = (
        ((doc.get("anomalies") or {}).get("dropped_displays") or {}).get("count")
        or ((doc.get("totals") or {}).get("invalid_displays_dropped") or {}).get("count")
        or ((doc.get("invalid_displays_dropped") or {}).get("count"))
    )
    assert isinstance(count, int) and count >= 0

# ---------- History invariants ----------

def test_history_entries_math_and_aliases(_load):
    doc = _load("history_parsing_summary.json")
    t = doc.get("totals") or {}

    assert t["entries_total"] == t["systems_total"] + t["software_total"]

    if "total_entries" in t and "total_systems" in t and "total_software" in t:
        assert t["total_entries"] == t["total_systems"] + t["total_software"]
        assert t["total_entries"] == t["entries_total"]
        assert t["total_systems"] == t["systems_total"]
        assert t["total_software"] == t["software_total"]

# ---------- INI invariants ----------

def test_ini_coverage_arithmetic(_load):
    doc = _load("ini_parsing_summary.json")
    t = doc.get("totals") or {}

    u = t["unique_machine_names_union"]
    with_gs = t["with_game_status"]
    with_cat = t["with_category"]
    with_type = t["with_type"]

    assert t["missing_in_game_status"] == u - with_gs
    assert t["missing_in_category"]    == u - with_cat
    assert t["missing_in_type"]        == u - with_type

# ---------- Transform invariants ----------

def test_transform_timings_and_partitions(_load):
    doc = _load("transform_summary.json")
    hdr = doc.get("header") or {}

    started = hdr.get("started_utc") or doc.get("started_utc")
    finished = hdr.get("finished_utc") or doc.get("finished_utc")
    assert _is_iso8601_z(started)
    assert _is_iso8601_z(finished)
    assert finished >= started

    counts = doc.get("counts") or {}
    eligible = counts.get("eligible_parents")
    included = counts.get("final_included")
    p_with = counts.get("parents_with_clones")
    p_without = counts.get("parents_without_clones")

    assert isinstance(eligible, int) and isinstance(included, int)
    assert included <= eligible

    if isinstance(p_with, int) and isinstance(p_without, int):
        assert p_with + p_without == eligible
