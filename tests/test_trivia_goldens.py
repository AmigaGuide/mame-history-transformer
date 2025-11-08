import json
import pytest
from pathlib import Path

from mht.utils.paths import gh_system_trivia_path
from tests.util_expectations import blocks_satisfy_expectations

FIXT_DIR = Path("tests/fixtures/trivia")


def _fixture_cases():
    # expected_subset.<system>.json  →  <system>
    for p in sorted(FIXT_DIR.glob("expected_subset.*.json")):
        system = p.stem.split(".", 1)[1]  # after first dot
        yield pytest.param(system, p.name, id=system)

@pytest.mark.parametrize("system, fixture_file", list(_fixture_cases()))
def test_trivia_expectations(system, fixture_file):
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
