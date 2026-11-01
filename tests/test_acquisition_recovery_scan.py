import json
from zipfile import ZipFile

from mht.provenance.acquisition import (
    build_acquisition_event,
    pending_acquisition_path,
    recover_staged_acquisitions,
    save_pending_acquisition_event,
)


def make_staged_archive(tmp_path):
    directory = tmp_path / "0289" / "archives"
    directory.mkdir(parents=True)

    archive = directory / "pS_CatVer_289.zip"

    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr(
            "UI_files/catlist.ini",
            ";; CATLIST.ini 0.289 / 21-Aug-26 / MAME 0.289 ;;\n"
            "[Arcade: Maze / Collect]\npuckman\n",
        )

    event = build_acquisition_event(
        archive,
        "https://example.com/pS_CatVer_289.zip",
        "0289",
        acquired_at="2026-11-01T14:00:00Z",
    )

    save_pending_acquisition_event(archive, event)

    return directory, archive, event


def test_recovers_staged_pending_event(tmp_path):
    directory, archive, event = make_staged_archive(tmp_path)

    results = recover_staged_acquisitions(
        "0289",
        archive_directory=directory,
    )

    assert len(results) == 1
    assert results[0]["action"] == "recovered"
    assert archive.exists()
    assert not pending_acquisition_path(archive).exists()

    manifest = directory.parent / "acquisition_manifest.json"
    assert manifest.exists()

    data = json.loads(manifest.read_text(encoding="utf-8"))
    record = data["archives"][0]

    assert record["sha256"] == event["sha256"]
    assert record["source_url"] == event["source_url"]
    assert record["acquired_at"] == event["acquired_at"]


def test_corrupt_pending_event_is_preserved(tmp_path):
    directory, archive, event = make_staged_archive(tmp_path)

    pending = pending_acquisition_path(archive)
    pending.write_text("invalid JSON", encoding="utf-8")

    results = recover_staged_acquisitions(
        "0289",
        archive_directory=directory,
    )

    assert results[0]["action"] == "error"
    assert results[0]["reason"] == "acquisition_recovery_failed"
    assert archive.exists()
    assert pending.exists()

    assert not (
        directory.parent / "acquisition_manifest.json"
    ).exists()


def test_changed_archive_preserves_pending_event(tmp_path):
    directory, archive, event = make_staged_archive(tmp_path)

    archive.write_bytes(b"replacement contents")

    results = recover_staged_acquisitions(
        "0289",
        archive_directory=directory,
    )

    assert results[0]["action"] == "error"
    assert pending_acquisition_path(archive).exists()

    assert not (
        directory.parent / "acquisition_manifest.json"
    ).exists()


def test_no_pending_events_requires_no_recovery(tmp_path):
    directory = tmp_path / "0289" / "archives"
    directory.mkdir(parents=True)

    results = recover_staged_acquisitions(
        "0289",
        archive_directory=directory,
    )

    assert results == []
