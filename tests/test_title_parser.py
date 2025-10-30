from mht.title.parser import parse_description


def test_simple_split_and_global():
    desc, anoms = parse_description('Title (Rev 2)')
    assert desc['title1'] == 'Title'
    assert desc['version1'] == ''     # single top-level group -> goes to global_version
    assert desc['global_version'] == 'Rev 2'
    assert not anoms['unbalanced_round_brackets']

def test_multi_units_versions():
    desc, _ = parse_description('Foo (Proto) / Bar (Rev 1)')
    assert desc['title1'] == 'Foo'
    assert desc['version1'] == 'Proto'
    assert desc['title2'] == 'Bar'
    assert desc['version2'] == 'Rev 1'
    assert desc['global_version'] == ''
