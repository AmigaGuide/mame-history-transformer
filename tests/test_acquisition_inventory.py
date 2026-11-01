from mht.provenance.acquisition import (
    identify_archive_source,
    inventory_release_archives,
)
from mht.utils.io import sha256_file


def test_identify_archive_sources():
    assert identify_archive_source("mame0289lx.zip") == "mame"
    assert identify_archive_source("history289a.zip") == "gaming_history"
    assert identify_archive_source("pS_CatVer_289.zip") == "snaps"
    assert identify_archive_source("pS_SupportFiles_288.zip") == "snaps"
    assert identify_archive_source("pS_Artwork_289.zip") == "unknown"


def test_inventory_three_upstream_archives(tmp_path):
    directory = tmp_path / "archives"
    directory.mkdir()

    filenames = (
        "mame0289lx.zip",
        "history289a.zip",
        "pS_CatVer_289.zip",
    )

    for filename in filenames:
        (directory / filename).write_bytes(
            f"test contents: {filename}".encode("utf-8")
        )

    records = inventory_release_archives(
        "0289",
        archive_directory=directory,
    )

    assert len(records) == 3

    by_name = {
        item["filename"]: item
        for item in records
    }

    assert by_name["mame0289lx.zip"]["source_type"] == "mame"
    assert by_name["history289a.zip"]["source_type"] == "gaming_history"
    assert by_name["pS_CatVer_289.zip"]["source_type"] == "snaps"

    for filename in filenames:
        record = by_name[filename]
        assert record["sha256"] == sha256_file(directory / filename)
        assert record["release"] == "0289"
        assert record["release_matches_filename"] is True
        assert record["source_url"] is None
        assert record["acquired_at"] is None


def test_inventory_preserves_release_mismatch(tmp_path):
    directory = tmp_path / "archives"
    directory.mkdir()

    (directory / "pS_CatVer_288.zip").write_bytes(
        b"test contents"
    )

    records = inventory_release_archives(
        "0289",
        archive_directory=directory,
    )

    assert records[0]["filename_release_hint"] == "0288"
    assert records[0]["release_matches_filename"] is False


def test_missing_archive_directory_returns_empty(tmp_path):
    records = inventory_release_archives(
        "0289",
        archive_directory=tmp_path / "missing",
    )

    assert records == []
