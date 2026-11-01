import json
from zipfile import ZipFile

from mht.provenance.acquisition import (
    build_acquisition_event,
    pending_acquisition_path,
    recover_stranded_acquisitions,
    save_pending_acquisition_event,
)


def prepare_stranded(tmp_path):
    incoming = tmp_path / "incoming"
    directory = tmp_path / "releases" / "0289" / "archives"
    incoming.mkdir(parents=True)
    directory.mkdir(parents=True)

    original = incoming / "pS_CatVer_289.zip"

    with ZipFile(original, "w") as archive:
        archive.writestr(
            "UI_files/catlist.ini",
            ";; CATLIST.ini 0.289 / 21-Aug-26 / MAME 0.289 ;;\n"
            "[Arcade: Maze / Collect]\npuckman\n",
        )

    event = build_acquisition_event(
        original,
        "https://example.com/pS_CatVer_289.zip",
        "0289",
        acquired_at="2026-11-01T14:00:00Z",
    )
    save_pending_acquisition_event(original, event)

    staged = directory / original.name
    original.replace(staged)

    return incoming, directory, original, staged, event


def test_recovers_stranded_incoming_event(tmp_path):
    incoming, directory, original, staged, event = (
        prepare_stranded(tmp_path)
    )

    results = recover_stranded_acquisitions(
        "0289",
        incoming_directory=incoming,
        archive_directory=directory,
    )

    assert len(results) == 1
    assert results[0]["action"] == "recovered"
    assert staged.exists()
    assert not pending_acquisition_path(original).exists()
    assert not pending_acquisition_path(staged).exists()

    manifest = directory.parent / "acquisition_manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    record = data["archives"][0]

    assert record["sha256"] == event["sha256"]
    assert record["source_url"] == event["source_url"]
    assert record["acquired_at"] == event["acquired_at"]


def test_changed_staged_archive_blocks_recovery(tmp_path):
    incoming, directory, original, staged, event = (
        prepare_stranded(tmp_path)
    )
    staged.write_bytes(b"changed contents")

    results = recover_stranded_acquisitions(
        "0289",
        incoming_directory=incoming,
        archive_directory=directory,
    )

    assert len(results) == 1
    assert results[0]["action"] == "error"
    assert pending_acquisition_path(original).exists()
    assert not (directory.parent / "acquisition_manifest.json").exists()


def test_incoming_archive_prevents_recovery(tmp_path):
    incoming, directory, original, staged, event = (
        prepare_stranded(tmp_path)
    )

    # An incoming ZIP means this is no longer clearly an
    # interrupted move. Ordinary ingestion owns that case.
    original.write_bytes(b"another incoming archive")

    results = recover_stranded_acquisitions(
        "0289",
        incoming_directory=incoming,
        archive_directory=directory,
    )

    assert results == []
    assert pending_acquisition_path(original).exists()
    assert staged.exists()
    assert not (directory.parent / "acquisition_manifest.json").exists()


def test_orphaned_pending_event_is_reported(tmp_path):
    incoming, directory, original, staged, event = (
        prepare_stranded(tmp_path)
    )

    # Simulate the staged ZIP disappearing after transfer.
    staged.unlink()

    results = recover_stranded_acquisitions(
        "0289",
        incoming_directory=incoming,
        archive_directory=directory,
    )

    assert len(results) == 1
    assert results[0]["action"] == "error"
    assert (
        results[0]["reason"]
        == "orphaned_pending_acquisition"
    )
    assert "no matching ZIP" in results[0]["error"]

    # Preserve the original evidence for investigation.
    assert pending_acquisition_path(original).exists()
    assert not (
        directory.parent / "acquisition_manifest.json"
    ).exists()


def test_orphan_detected_without_release_directory(tmp_path):
    incoming, directory, original, staged, event = (
        prepare_stranded(tmp_path)
    )

    staged.unlink()
    directory.rmdir()

    results = recover_stranded_acquisitions(
        "0289",
        incoming_directory=incoming,
        archive_directory=directory,
    )

    assert len(results) == 1
    assert results[0]["reason"] == "orphaned_pending_acquisition"
    assert pending_acquisition_path(original).exists()


def test_unrelated_release_ignores_pending_event(tmp_path):
    incoming, directory, original, staged, event = (
        prepare_stranded(tmp_path)
    )

    staged.unlink()

    results = recover_stranded_acquisitions(
        "0288",
        incoming_directory=incoming,
        archive_directory=directory,
    )

    assert results == []
    assert pending_acquisition_path(original).exists()
