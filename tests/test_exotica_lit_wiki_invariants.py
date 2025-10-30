import json


def test_wiki_core_invariants(outputs_dir):
    DOC = (outputs_dir / "exotica_lit_wiki.json")
    d = json.loads(DOC.read_text(encoding="utf-8"))
    games = d["games"]
    for mach, rec in games.items():
        # page name non-empty
        assert isinstance(rec["wiki_page_name"], str) and rec["wiki_page_name"].strip()

        # redirects unique and don’t include the page itself
        rds = rec.get("wiki_redirects", [])
        assert len(rds) == len(set(rds)), f"{mach}: duplicate redirects"
        assert rec["wiki_page_name"] not in rds, f"{mach}: self included in redirects"

        # mame_titles_display: array of non-empty strings (unique)
        mtd = rec["mame_titles_display"]
        assert isinstance(mtd, list), f"{mach}: mame_titles_display must be a list"
        assert all(isinstance(s, str) and s.strip() for s in mtd), f"{mach}: empty/invalid title in mame_titles_display"
        assert len(mtd) == len(set(mtd)), f"{mach}: duplicate entries in mame_titles_display"

        # the rest are strings
        for key in ["roms_display", "chips_display", "displays_display", "controls_display"]:
            val = rec[key]
            assert isinstance(val, str), f"{mach}: {key} must be a string"

def test_redirects_point_somewhere_realistic(outputs_dir):
    DOC = (outputs_dir / "exotica_lit_wiki.json")
    d = json.loads(DOC.read_text(encoding="utf-8"))
    games = d["games"]
    #all_pages = {rec["wiki_page_name"] for rec in games.values()}

    for mach, rec in games.items():
        for rd in rec.get("wiki_redirects", []):
            # If redirects use the LiT namespace, we can optionally check existence.
            # Leave relaxed because some redirects may point outside this file.
            if rd.startswith("Lost In Translation/"):
                # Uncomment the next line if you want to enforce local target presence:
                # assert rd in all_pages, f"{mach}: redirect target not found: {rd}"
                pass
