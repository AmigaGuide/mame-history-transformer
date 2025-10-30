from mht.utils.titles import parse_description, build_redirect_sources


def test_parse_single_unit_with_version():
    desc, anomalies = parse_description('Pac-Land (Rev B)')
    assert desc["title1"] == "Pac-Land"
    assert desc["global_version"] != ""  # carries "(Rev B)"
    assert not anomalies["unbalanced_round_brackets"]

def test_parse_multi_unit_and_redirects():
    desc, _ = parse_description('Wonder Boy / Monster Land')
    assert desc["title1"] == "Wonder Boy"
    assert desc["title2"] == "Monster Land"
    page = "Wonder Boy"
    redirects = build_redirect_sources(desc, page)
    assert "Monster Land" in redirects
