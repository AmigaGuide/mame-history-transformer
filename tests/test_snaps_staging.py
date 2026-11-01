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


from mht.provenance.acquisition import (
    build_acquisition_event,
    pending_acquisition_path,
    save_pending_acquisition_event,
)
import json


def test_staging_preserves_download_provenance(
    monkeypatch,
    tmp_path,
):
    incoming = tmp_path / "incoming"
    incoming.mkdir()

    source = incoming / "pS_CatVer_289.zip"

    with ZipFile(source, "w") as archive:
        archive.writestr(
            "UI_files/catlist.ini",
            ";; CATLIST.ini 0.289 / 21-Aug-26 / MAME 0.289 ;;\n"
            "[Arcade: Maze / Collect]\npuckman\n",
        )

    event = build_acquisition_event(
        source,
        "https://www.progettosnaps.net/download/",
        "0289",
        acquired_at="2026-11-01T14:00:00Z",
    )

    save_pending_acquisition_event(source, event)

    releases = tmp_path / "releases"

    monkeypatch.setattr(
        archives,
        "archives_dir",
        lambda ver: releases / ver / "archives",
    )

    # Keep the manifest audit inside the test's temporary directory.
    from mht.provenance import acquisition

    monkeypatch.setattr(
        acquisition,
        "archives_dir",
        lambda ver: releases / ver / "archives",
    )

    result = archives.import_incoming_archives(
        incoming=incoming,
    )

    assert result[0]["action"] == "moved"

    staged = releases / "0289" / "archives" / source.name

    assert staged.exists()
    assert not source.exists()
    assert not pending_acquisition_path(source).exists()
    assert not pending_acquisition_path(staged).exists()

    manifest_path = releases / "0289" / "acquisition_manifest.json"

    assert manifest_path.exists()

    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

    record = manifest["archives"][0]

    assert record["verification_status"] == "verified"
    assert record["source_url"] == event["source_url"]
    assert record["acquired_at"] == event["acquired_at"]
    assert record["sha256"] == event["sha256"]


def test_staging_preserves_pending_event_when_manifest_fails(
    monkeypatch,
    tmp_path,
):
    from mht.provenance import acquisition

    incoming = tmp_path / "incoming"
    incoming.mkdir()

    source = incoming / "pS_CatVer_289.zip"
    make_snaps(source)

    event = build_acquisition_event(
        source,
        "https://example.com/pS_CatVer_289.zip",
        "0289",
        acquired_at="2026-11-01T14:00:00Z",
    )
    save_pending_acquisition_event(source, event)

    releases = tmp_path / "releases"

    monkeypatch.setattr(
        archives,
        "archives_dir",
        lambda version: releases / version / "archives",
    )

    def failed_manifest(*args, **kwargs):
        raise OSError("Simulated manifest write failure")

    monkeypatch.setattr(
        acquisition,
        "save_acquisition_manifest",
        failed_manifest,
    )

    result = archives.import_incoming_archives(
        incoming=incoming,
    )

    staged = releases / "0289" / "archives" / source.name

    assert result[0]["action"] == "error"
    assert result[0]["reason"] == "acquisition_provenance_pending"
    assert staged.exists()
    assert not source.exists()

    # Provenance remains available for recovery.
    assert pending_acquisition_path(staged).exists()

    # No misleading success manifest has been created.
    assert not (
        releases / "0289" / "acquisition_manifest.json"
    ).exists()
