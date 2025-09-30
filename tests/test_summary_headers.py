from pathlib import Path
import json
import pytest

# Use the central truth
from mht.utils.versions import SCHEMA_IDS, schema_version

DATA = Path("data")

def _load(path: Path):
    if not path.exists():
        pytest.skip(f"missing: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)

@pytest.mark.parametrize(
    "fname,schema_key",
    [
        ("mame_parsing_summary.json", "mame"),
        ("history_parsing_summary.json", "history"),
        ("ini_parsing_summary.json", "ini"),
        ("transform_summary.json", "transform"),
    ],
)
def test_header_standardised(fname, schema_key):
    doc = _load(DATA / fname)
    hdr = doc.get("header") or {}
    assert hdr.get("schema_id") == SCHEMA_IDS[schema_key]
    assert hdr.get("schema_version") == schema_version(SCHEMA_IDS[schema_key])
    assert isinstance(hdr.get("generated_at"), str) and hdr["generated_at"]  # non-empty
    assert isinstance(hdr.get("versions"), dict)

def test_mame_aliases():
    doc = _load(DATA / "mame_parsing_summary.json")
    totals = doc.get("totals") or {}
    # Only assert when both sides present (additive, non-breaking)
    if "total_isbios" in totals and "total_is_bios" in totals:
        assert totals["total_is_bios"] == totals["total_isbios"]
    if "total_isdevice" in totals and "total_is_device" in totals:
        assert totals["total_is_device"] == totals["total_isdevice"]

def test_history_aliases():
    doc = _load(DATA / "history_parsing_summary.json")
    totals = doc.get("totals") or {}
    if "systems_total" in totals and "total_systems" in totals:
        assert totals["total_systems"] == totals["systems_total"]
    if "software_total" in totals and "total_software" in totals:
        assert totals["total_software"] == totals["software_total"]
    if "entries_total" in totals and "total_entries" in totals:
        assert totals["total_entries"] == totals["entries_total"]

def test_transform_versions_present():
    doc = _load(DATA / "transform_summary.json")
    v = (doc.get("header") or {}).get("versions") or {}
    # These should be populated from the stage summaries
    assert isinstance(v.get("mame_build"), str) and v["mame_build"]
    assert isinstance(v.get("history_version"), str) and v["history_version"]
    assert isinstance(v.get("history_date"), str) and v["history_date"]
    assert isinstance(v.get("ini_generated_at"), str) and v["ini_generated_at"]
