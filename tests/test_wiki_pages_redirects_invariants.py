import json
import pathlib
import pytest

PAGES_PATH = pathlib.Path("output/exotica_wiki_pages_and_redirects.json")

def load_doc():
    return json.loads(PAGES_PATH.read_text(encoding="utf-8"))

def test_prefix_and_sets_are_consistent():
    d = load_doc()
    prefix     = d["prefix"]
    pages      = d["pages"]
    page_names = d["page_names"]
    redirects  = d["redirects"]
    stats      = d["stats"]

    # page_names must be unique by schema, but also check counts vs stats
    assert len(page_names) == stats["page_names_total"]

    # Every pages[] value should start with prefix and be listed in page_names
    pn_set = set(page_names)
    for mach, path in pages.items():
        assert path.startswith(prefix), f"{mach}: path '{path}' doesn't start with prefix '{prefix}'"
        assert path in pn_set, f"{mach}: path '{path}' not found in page_names"

    # Every redirect target must be a known page_name; keys should also use the prefix
    for src, dst in redirects.items():
        assert src.startswith(prefix), f"redirect source '{src}' missing prefix '{prefix}'"
        assert dst.startswith(prefix), f"redirect target '{dst}' missing prefix '{prefix}'"
        assert dst in pn_set, f"redirect target '{dst}' not present in page_names"

    # No self-redirects
    bad_self = [k for k, v in redirects.items() if k == v]
    assert not bad_self, f"self-redirects found: {bad_self}"

def test_stats_match_lengths_and_conflicts_shape():
    d = load_doc()
    stats     = d["stats"]
    pages     = d["pages"]
    redirects = d["redirects"]
    conf      = d["conflicts"]

    # Simple count checks
    assert len(pages)     == stats["parents_total"]
    assert len(redirects) == stats["redirects_total"]
    assert len(conf.get("page_name_collisions", [])) == stats["page_name_collisions"]
    assert len(conf.get("redirect_conflicts", []))   == stats["redirect_conflicts"]

    # Collision entries: at least 2 machines, unique, valid-looking names
    for c in conf.get("page_name_collisions", []):
        ms = c["machines"]
        assert len(ms) >= 2
        assert len(ms) == len(set(ms))
        for m in ms:
            assert isinstance(m, str) and m, "machine name must be non-empty"

    # Redirect conflict entries: at least 2 targets and 2 machines; uniqueness
    for rc in conf.get("redirect_conflicts", []):
        ts = rc["targets"]; ms = rc["machines"]
        assert len(ts) >= 2 and len(set(ts)) == len(ts)
        assert len(ms) >= 2 and len(set(ms)) == len(ms)
