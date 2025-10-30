import json


def test_basic_invariants(outputs_dir):
    DOC = (outputs_dir / "gh_ini_classifications.json")
    data = json.loads(DOC.read_text(encoding="utf-8"))

    assert isinstance(data, dict) and data, "expected top-level object with entries"

    for mach, rec in data.items():
        # machine key shape
        assert mach and mach == mach.lower()
        assert all(c.isalnum() or c == "_" for c in mach), f"bad key: {mach}"

        # required fields guaranteed by schema, but add a couple of value checks:
        cats = rec["category"]
        assert isinstance(cats, list) and len(cats) >= 1
        assert all(isinstance(s, str) and s.strip() for s in cats), f"{mach}: empty category value"

        t = rec["type"]
        assert isinstance(t, str) and t.strip(), f"{mach}: empty type"

        gs = rec["game_status"]
        assert gs in {"game", "no_game", "unknown"}
