import json
import pytest
from pathlib import Path

from mht.utils.paths import gh_system_trivia_path, history_summary_path
from mht.utils.validator import validate_trivia_file_against_schema
from tests.util_json_subset import is_subset
from tests.util_expectations import blocks_satisfy_expectations


FIXT_DIR = Path(__file__).parent / "_fixtures" / "trivia"

@pytest.mark.order(1)
def test_trivia_schema_validates():
    # Warn-only inside CLI, but here we want a hard assertion.
    ok = validate_trivia_file_against_schema(gh_system_trivia_path(), warn_only=False)
    assert ok

def _fixture_cases():
    # mirrors test_trivia_goldens.py discovery pattern
    for p in sorted(FIXT_DIR.glob("expected_subset.*.json")):
        system = p.stem.split(".")[1]  # expected_subset.<system>.json
        yield system, p.name

@pytest.mark.parametrize("system, fixture_file", list(_fixture_cases()))
def test_trivia_blocks_match_goldens(system, fixture_file):
    """
    Use the SAME expectation engine as tests/test_trivia_goldens.py
    so our flexible anchors (text_contains, any_text_contains, etc.)
    are honoured instead of doing a literal JSON subset comparison.
    """
    trivia = json.loads(gh_system_trivia_path().read_text(encoding="utf-8"))
    assert system in trivia, f"{system} missing in gh_system_trivia.json"

    fx = json.loads((FIXT_DIR / fixture_file).read_text(encoding="utf-8"))
    exp_sections = (fx.get("expectations") or {}).get("sections") or {}
    sys_sections = (trivia[system] or {}).get("sections") or {}

    for sec_name, sec_expect in exp_sections.items():
        assert sec_name in sys_sections, f"{system}:{sec_name} missing"
        exp_blocks = (sec_expect or {}).get("blocks") or []
        act_blocks = (sys_sections[sec_name] or {}).get("blocks") or []
        assert act_blocks, f"{system}:{sec_name} has no blocks"
        ok = blocks_satisfy_expectations(exp_blocks, act_blocks)
        assert ok, f"{system}:{sec_name} blocks do not satisfy expectations"

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
