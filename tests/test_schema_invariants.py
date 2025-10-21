import pytest
from jsonschema import Draft202012Validator

# name, schema (repo-relative), output filename (under releases/<ver>/outputs)
CASES = [
    ("raw_data",   "src/mht/contracts/exotica_lit_raw_data.schema.json",                "exotica_lit_raw_data.json"),
    ("wiki",       "src/mht/contracts/exotica_lit_wiki.schema.json",                   "exotica_lit_wiki.json"),
    ("wiki_pages", "src/mht/contracts/exotica_wiki_pages_and_redirects.schema.json",   "exotica_wiki_pages_and_redirects.json"),
    ("gh_ini",     "src/mht/contracts/gh_ini_classifications.schema.json",             "gh_ini_classifications.json"),
    ("gh_ports",   "src/mht/contracts/gh_system_ports.schema.json",                    "gh_system_ports.json"),
    ("mame_mach",  "src/mht/contracts/mame_machines.schema.json",                      "mame_machines.json"),
    ("parent_idx", "src/mht/contracts/mame_parent_index.schema.json",                  "mame_parent_index.json"),
]

@pytest.mark.parametrize("name,schema_rel,doc_leaf", CASES)
def test_output_validates_against_schema(name, schema_rel, doc_leaf, project_root, outputs_dir, read_json):
    schema_path = project_root / schema_rel
    doc_path = outputs_dir / doc_leaf

    schema = read_json(schema_path)
    doc = read_json(doc_path)

    v = Draft202012Validator(schema)
    errors = sorted(v.iter_errors(doc), key=lambda e: (list(e.path), e.message))
    assert not errors, (
        f"{name} failed:\n" +
        "\n".join(f"/{'/'.join(map(str, e.path))} -> {e.message}" for e in errors)
    )
