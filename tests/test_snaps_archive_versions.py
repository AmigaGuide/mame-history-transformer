import pytest

from mht.provenance.peek import (
    derive_mame_version_hint_from_filename,
)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("pS_SupportFiles_287.zip", "0287"),
        ("pS_SupportFiles_288.zip", "0288"),
        ("pS_CatVer_289.zip", "0289"),
        ("ps_catver_289.ZIP", "0289"),
        ("mame0287lx.zip", "0287"),
        ("history287a.zip", "0287"),
    ],
)
def test_release_detection(filename, expected):
    assert (
        derive_mame_version_hint_from_filename(filename)
        == expected
    )


@pytest.mark.parametrize(
    "filename",
    [
        "pS_Artwork_289.zip",
        "pS_CatVer_latest.zip",
        "pS_CatVer_289_backup.zip",
        "pS_CatVer_289.zip.tmp",
    ],
)
def test_unrecognised_snaps_filenames(filename):
    assert derive_mame_version_hint_from_filename(
        filename
    ) is None
