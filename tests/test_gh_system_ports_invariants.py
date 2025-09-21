import json
import pathlib

DOC = pathlib.Path("output/gh_system_ports.json")

def test_basic_uniqueness_and_alias_hygiene():
    data = json.loads(DOC.read_text(encoding="utf-8"))

    # gh_id must be unique across all systems
    seen = {}
    dupes = []
    for mach, rec in data.items():
        gid = rec.get("gh_id")
        if gid in seen:
            dupes.append((gid, seen[gid], mach))
        else:
            seen[gid] = mach
    assert not dupes, f"Duplicate gh_id detected: {dupes[:5]}"

    # a system must not list itself among its aliases
    bad = [m for m, rec in data.items() if m in set(rec.get("aliases", []))]
    assert not bad, f"Systems listed as their own alias: {bad}"

def test_ports_categories_and_regions():
    data = json.loads(DOC.read_text(encoding="utf-8"))
    allowed = {"CONSOLES", "HANDHELDS", "COMPUTERS", "OTHERS"}

    for mach, rec in data.items():
        ports = rec.get("ports", {})
        # category keys must be subset of the allowed set (schema already enforces)
        assert set(ports.keys()) <= allowed, f"{mach}: unexpected category keys {set(ports.keys()) - allowed}"
        # region codes (if present) should be two letters or '??'
        for cat, items in ports.items():
            for it in items:
                for r in it.get("regions", []):
                    assert isinstance(r, str) and len(r) == 2 and r.isupper() or r == "??", f"{mach}/{cat}: bad region '{r}'"
