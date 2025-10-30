import pytest


@pytest.fixture(scope="module")
def load_doc(outputs_dir, read_json):
    """Load the wiki pages/redirects doc once for this module."""
    return read_json(outputs_dir / "exotica_wiki_pages_and_redirects.json")

def test_prefix_and_sets_are_consistent(load_doc):
    d = load_doc
    prefix     = d["prefix"]
    pages      = d["pages"]
    page_names = d["page_names"]
    redirects  = d["redirects"]
    stats      = d["stats"]

    assert len(page_names) == stats["page_names_total"]

    pn_set = set(page_names)
    for mach, path in pages.items():
        assert path.startswith(prefix), f"{mach}: path '{path}' doesn't start with prefix '{prefix}'"
        assert path in pn_set, f"{mach}: path '{path}' not found in page_names"

    for src, dst in redirects.items():
        assert src.startswith(prefix), f"redirect source '{src}' missing prefix '{prefix}'"
        assert dst.startswith(prefix), f"redirect target '{dst}' missing prefix '{prefix}'"
        assert dst in pn_set, f"redirect target '{dst}' not present in page_names"

    bad_self = [k for k, v in redirects.items() if k == v]
    assert not bad_self, f"self-redirects found: {bad_self}"

def test_stats_match_lengths_and_conflicts_shape(load_doc):
    d = load_doc
    stats     = d["stats"]
    pages     = d["pages"]
    redirects = d["redirects"]
    conf      = d["conflicts"]

    assert len(pages)     == stats["parents_total"]
    assert len(redirects) == stats["redirects_total"]
    assert len(conf.get("page_name_collisions", [])) == stats["page_name_collisions"]
    assert len(conf.get("redirect_conflicts", []))   == stats["redirect_conflicts"]

    for c in conf.get("page_name_collisions", []):
        ms = c["machines"]
        assert len(ms) >= 2
        assert len(ms) == len(set(ms))
        for m in ms:
            assert isinstance(m, str) and m

    for rc in conf.get("redirect_conflicts", []):
        ts = rc["targets"]; ms = rc["machines"]
        assert len(ts) >= 2 and len(set(ts)) == len(ts)
        assert len(ms) >= 2 and len(set(ms)) == len(ms)
