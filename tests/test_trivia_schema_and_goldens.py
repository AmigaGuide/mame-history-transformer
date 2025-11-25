import json
import pathlib
import pytest

from mht.utils.paths import gh_system_trivia_path, history_summary_path
from mht.utils.validator import validate_trivia_file_against_schema
from tests.util_expectations import blocks_satisfy_expectations


FIXT_DIR = pathlib.Path(__file__).parent / "fixtures" / "trivia"


def test_trivia_schema_validates():
    # Warn-only inside CLI, but here we want a hard assertion.
    ok = validate_trivia_file_against_schema(gh_system_trivia_path(), warn_only=False)
    assert ok

def _fixture_cases():
    """
    Auto-discover expected_subset.<system>.json in our fixtures dir.
    Yields (system, filename) tuples for parametrisation.
    """
    cases = []
    for p in sorted(FIXT_DIR.glob("expected_subset.*.json")):
        # Files are named expected_subset.<system>.json
        parts = p.name.split(".")
        if len(parts) == 3 and parts[0] == "expected_subset" and parts[2] == "json":
            system = parts[1]
            cases.append((system, p.name))
    return cases

@pytest.mark.parametrize("system, fixture_file", list(_fixture_cases()))
def test_trivia_blocks_match_goldens(system, fixture_file):
    """
    Schema+goldens guard: for each discovered expected_subset.<system>.json,
    assert the parsed trivia blocks satisfy the subset expectations.
    """
    # Path to the parsed JSON produced by your pipeline
    # (this helper is already present in the file below; leaving as-is)
    trivia = json.loads(gh_system_trivia_path().read_text(encoding="utf-8"))
    assert system in trivia, f"{system} missing in gh_system_trivia.json"

    fx = json.loads((FIXT_DIR / fixture_file).read_text(encoding="utf-8"))
    exp_sections = fx.get("expectations", {}).get("sections", {})
    sys_sections = trivia[system].get("sections", {})

    for sec_name, sec_expect in exp_sections.items():
        assert sec_name in sys_sections, f"{system}:{sec_name} missing"
        exp_blocks = (sec_expect or {}).get("blocks", [])
        act_blocks = (sys_sections[sec_name] or {}).get("blocks", [])
        assert act_blocks, f"{system}:{sec_name} has no blocks"
        assert blocks_satisfy_expectations(exp_blocks, act_blocks), \
            f"{system}:{sec_name} blocks do not satisfy expectations"

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
