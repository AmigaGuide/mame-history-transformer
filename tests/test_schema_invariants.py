import json, pathlib
from jsonschema import Draft202012Validator

SCHEMA = json.loads(pathlib.Path("src/mht/contracts/exotica_lit_raw_data.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)

def test_schema_validates_current_output():
    doc = json.loads(pathlib.Path("output/exotica_lit_raw_data.json").read_text(encoding="utf-8"))
    errors = list(VALIDATOR.iter_errors(doc))
    assert not errors, "\n".join(f"/{'/'.join(map(str,e.path))} -> {e.message}" for e in errors)
