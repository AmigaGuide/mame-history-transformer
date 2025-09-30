from pathlib import Path
import json
import pytest

from mht.versions import output_schema

OUT = Path("output")

CASES = [
    ("exotica_lit_wiki.json", "wiki"),
    ("exotica_lit_raw_data.json", "raw"),
    ("exotica_wiki_pages_and_redirects.json", "pages"),
]

def _load(path: Path):
    if not path.exists():
        pytest.skip(f"missing: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)

@pytest.mark.parametrize("fname,key", CASES)
def test_output_schema_id_and_version(fname, key):
    d = _load(OUT / fname)
    # Only assert if the fields are present in the file format
    want = output_schema(key)
    sid = d.get("schema_id")
    sver = d.get("schema_version")
    if sid is not None:
        assert sid == want["id"]
    if sver is not None:
        assert sver == want["version"]
