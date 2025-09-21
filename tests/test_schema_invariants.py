import json, pathlib, pytest
from jsonschema import Draft202012Validator

CASES = [
    (
        "raw_data",
        "src/mht/contracts/exotica_lit_raw_data.schema.json",
        "output/exotica_lit_raw_data.json",
    ),
    (
        "wiki",
        "src/mht/contracts/exotica_lit_wiki.schema.json",
        "output/exotica_lit_wiki.json",
    ),
]

@pytest.mark.parametrize("name,schema_path,doc_path", CASES)
def test_output_validates_against_schema(name, schema_path, doc_path):
    schema = json.loads(pathlib.Path(schema_path).read_text(encoding="utf-8"))
    doc    = json.loads(pathlib.Path(doc_path).read_text(encoding="utf-8"))
    v = Draft202012Validator(schema)
    errors = list(v.iter_errors(doc))
    assert not errors, f"{name} failed:\n" + "\n".join(
        f"/{'/'.join(map(str,e.path))} -> {e.message}"
        for e in sorted(errors, key=lambda e: (list(e.path), e.message))
    )
