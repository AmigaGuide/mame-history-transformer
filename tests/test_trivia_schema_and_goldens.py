import json
import pytest
from pathlib import Path

from mht.utils.paths import gh_system_trivia_path, history_summary_path
from mht.utils.validator import validate_trivia_file_against_schema
from tests.util_json_subset import is_subset

FIXT = Path("tests/fixtures/trivia")

@pytest.mark.order(1)
def test_trivia_schema_validates():
    # Warn-only inside CLI, but here we want a hard assertion.
    ok = validate_trivia_file_against_schema(gh_system_trivia_path(), warn_only=False)
    assert ok

@pytest.mark.parametrize("system, fixture_name", [
    ("puckman", "expected_subset.puckman.json"),
    ("outrun",  "expected_subset.outrun.json"),
    ("005",     "expected_subset.005.json"),
    ("sf2j",    "expected_subset.sf2j.json"),
])
def test_trivia_blocks_match_goldens(system, fixture_name):
    trivia = json.loads(gh_system_trivia_path().read_text(encoding="utf-8"))
    assert system in trivia, f"System {system} missing in gh_system_trivia.json"

    # Only assert subset to keep tests stable across suppression/refinements
    expected = json.loads((FIXT / fixture_name).read_text(encoding="utf-8"))
    assert is_subset(expected, trivia[system]), f"{system} does not satisfy expected subset"

def test_trivia_provenance_is_sane_for_sample():
    trivia = json.loads(gh_system_trivia_path().read_text(encoding="utf-8"))
    sample = trivia.get("puckman")
    assert sample and "sections" in sample
    ov = sample["sections"].get("overview", {})
    blocks = ov.get("blocks", [])
    assert blocks, "overview must have blocks after suppression"

    # basic provenance shape check on first block (no hashing assumptions)
    m = blocks[0].get("meta", {})
    assert m.get("system") == "puckman"
    assert isinstance(m.get("block_index"), int) and m["block_index"] >= 0
    assert isinstance(m.get("filtered_line_start"), int)
    assert isinstance(m.get("filtered_line_end"), int)
    assert isinstance(m.get("detectors"), list) and m["detectors"]
    assert isinstance(m.get("suppressions"), list)

def test_summary_reports_new_sections():
    summary = json.loads(history_summary_path().read_text(encoding="utf-8"))
    found = summary.get("found", {})
    assert "blocks" in found and "by_type" in found["blocks"]
    assert "provenance" in summary and "policy_counts" in summary["provenance"]
    assert "headings_qc" in summary and "near_miss_banners" in summary["headings_qc"]
