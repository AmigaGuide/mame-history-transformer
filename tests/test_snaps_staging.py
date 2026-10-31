from pathlib import Path
from zipfile import ZipFile

from mht.provenance import archives


def make_snaps(path: Path):
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "CatVer/catlist.ini",
            "[Arcade: Maze / Collect]\npuckman\n",
        )


def test_snaps_is_staged_to_its_own_release(
    monkeypatch,
    tmp_path,
):
    incoming = tmp_path / "incoming"
    incoming.mkdir()

    source = incoming / "pS_CatVer_289.zip"
    make_snaps(source)

    releases = tmp_path / "releases"

    monkeypatch.setattr(
        archives,
        "archives_dir",
        lambda ver: releases / ver / "archives",
    )

    result = archives.import_incoming_archives(
        incoming=incoming,
    )

    assert result[0]["action"] == "moved"
    assert result[0]["version"] == "0289"
    assert (
        releases / "0289" / "archives" / source.name
    ).exists()


def test_existing_snaps_archive_is_not_duplicated(
    monkeypatch,
    tmp_path,
):
    incoming = tmp_path / "incoming"
    incoming.mkdir()

    source = incoming / "pS_CatVer_289.zip"
    make_snaps(source)

    releases = tmp_path / "releases"
    staged = releases / "0289" / "archives"
    staged.mkdir(parents=True)

    existing = staged / "pS_SupportFiles_289.zip"
    make_snaps(existing)

    monkeypatch.setattr(
        archives,
        "archives_dir",
        lambda ver: releases / ver / "archives",
    )

    result = archives.import_incoming_archives(
        incoming=incoming,
    )

    assert result[0]["action"] == "skipped"
    assert result[0]["reason"] == "snaps_already_staged"
    assert existing.exists()
    assert source.exists()
    assert not (staged / source.name).exists()


def test_forced_release_mismatch_is_rejected(
    monkeypatch,
    tmp_path,
):
    incoming = tmp_path / "incoming"
    incoming.mkdir()

    source = incoming / "pS_CatVer_289.zip"
    make_snaps(source)

    result = archives.import_incoming_archives(
        incoming=incoming,
        version="0287",
    )

    assert result[0]["action"] == "rejected"
    assert result[0]["reason"] == "snaps_release_mismatch"
    assert source.exists()


def test_invalid_existing_snaps_is_rejected_without_changes(
    monkeypatch,
    tmp_path,
):
    incoming = tmp_path / "incoming"
    incoming.mkdir()

    source = incoming / "pS_CatVer_289.zip"
    make_snaps(source)
    original = source.read_bytes()

    releases = tmp_path / "releases"
    staged = releases / "0289" / "archives"
    staged.mkdir(parents=True)

    existing = staged / "pS_SupportFiles_289.zip"
    existing.write_bytes(b"corrupt archive")

    monkeypatch.setattr(
        archives,
        "archives_dir",
        lambda ver: releases / ver / "archives",
    )

    result = archives.import_incoming_archives(
        incoming=incoming,
    )

    assert result[0]["action"] == "rejected"
    assert result[0]["reason"] == "invalid_existing_snaps"

    assert source.exists()
    assert source.read_bytes() == original
    assert existing.read_bytes() == b"corrupt archive"
    assert not (staged / source.name).exists()
