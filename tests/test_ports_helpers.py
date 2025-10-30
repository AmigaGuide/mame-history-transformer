from mht.utils.ports import norm_regions, norm_tags


def test_norm_regions_roundtrip_and_type():
    inp = ["US", "jp", "EU"]
    out = norm_regions(inp)
    # current behavior: pass-through; keep order/case
    assert out == inp
    assert isinstance(out, list)
    assert len(out) == len(inp)

def test_norm_tags_passthrough_and_contains():
    inp = ["compilation", "Remaster"]
    out = norm_tags(inp)
    # current behavior: pass-through (no title-casing)
    assert "compilation" in out
    assert "Remaster" in out
    assert isinstance(out, list)
