from zipfile import ZipFile

import pytest

from mht.provenance.snaps_sources import SnapsSource
from mht.provenance.snaps_validation import validate_snaps_archive


def source(filename="pS_CatVer_289.zip"):
    return SnapsSource(
        release="0289",
        package_type="catver",
        filename=filename,
        url="https://www.progettosnaps.net/download/",
    )


def test_valid_catver_archive(tmp_path):
    path = tmp_path / "pS_CatVer_289.zip"

    with ZipFile(path, "w") as archive:
        archive.writestr(
            "CatVer/catlist.ini",
            "[Arcade: Maze / Collect]\npuckman\n",
        )

    result = validate_snaps_archive(path, source())

    assert result["release"] == "0289"
    assert result["catlist_member"] == "CatVer/catlist.ini"
    assert result["classifications"] == 1


def test_archive_without_catlist_is_rejected(tmp_path):
    path = tmp_path / "pS_CatVer_289.zip"

    with ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", "Nothing here")

    with pytest.raises(ValueError, match="Expected one CatList"):
        validate_snaps_archive(path, source())


from mht.provenance.snaps_validation import extract_catlist_metadata


def test_catlist_header_metadata():
    content = """
[FOLDER_SETTINGS]
RootFolderIcon mame

;; CATLIST.ini 0.289 / 21-Aug-26 / MAME 0.289 ;;

[ROOT_FOLDER]
[Arcade: Maze / Collect]
puckman
"""

    metadata = extract_catlist_metadata(content)

    assert metadata == {
        "catlist_version": "0.289",
        "mame_version": "0.289",
        "source_date": "21-Aug-26",
    }


def test_embedded_version_mismatch_is_rejected(tmp_path):
    path = tmp_path / "pS_CatVer_289.zip"

    with ZipFile(path, "w") as archive:
        archive.writestr(
            "UI_files/catlist.ini",
            ";; CATLIST.ini 0.288 / 01-Jul-26 / MAME 0.288 ;;\n"
            "[Arcade: Maze / Collect]\npuckman\n",
        )

    with pytest.raises(ValueError, match="SNAPS release mismatch"):
        validate_snaps_archive(path, source())


def test_legacy_catlist_without_header_remains_supported(tmp_path):
    path = tmp_path / "pS_CatVer_289.zip"

    with ZipFile(path, "w") as archive:
        archive.writestr(
            "CatVer/catlist.ini",
            "[Arcade: Maze / Collect]\npuckman\n",
        )

    result = validate_snaps_archive(path, source())

    assert result["embedded_metadata"]["mame_version"] is None
    assert result["classifications"] == 1
