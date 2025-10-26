import pytest

from mht.provenance.peek import derive_mame_version_hint_from_filename as hint

@pytest.mark.parametrize("name,expected", [
    ("mame0281lx.zip", "0281"),
    ("MAME-0282-WIN.ZIP", "0282"),
    ("mame-0.279-win.zip", "0279"),
    ("mame281.zip", "0281"),
    ("foo.zip", None),
    ("some-0.263-file.zip", "0263"),
    ("mame_0280_source.7z", "0280"),
])
def test_filename_to_version_hint(name, expected):
    assert hint(name) == expected
