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
    (
        "wiki_pages", 
        "src/mht/contracts/exotica_wiki_pages_and_redirects.schema.json",
        "output/exotica_wiki_pages_and_redirects.json",
    ),
    (
        "gh_ini",   
        "src/mht/contracts/gh_ini_classifications.schema.json",
        "output/gh_ini_classifications.json"
    ),
    (
        "gh_ports", 
        "src/mht/contracts/gh_system_ports.schema.json",       
        "output/gh_system_ports.json"
    ),
    (
        "mame_mach", 
        "src/mht/contracts/mame_machines.schema.json",                        
        "output/mame_machines.json",
    ),
    (
        "parent_idx", 
        "src/mht/contracts/mame_parent_index.schema.json",                    
        "output/mame_parent_index.json"
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
