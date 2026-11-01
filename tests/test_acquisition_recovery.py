import json
from zipfile import ZipFile

import pytest

from mht.provenance.acquisition import (
    build_acquisition_event,
    finalise_staged_acquisition,
    pending_acquisition_path,
    save_pending_acquisition_event,
)


def prepare_staged_archive(tmp_path, *, transfer_event=False):
    incoming = tmp_path / "incoming"
    staged_dir = tmp_path / "releases" / "0289" / "archives"

    incoming.mkdir(parents=True)
    staged_dir.mkdir(parents=True)

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

    staged = staged_dir / original.name
    original.replace(staged)

    if transfer_event:
        pending_acquisition_path(original).replace(
            pending_acquisition_path(staged)
        )

    manifest = staged_dir.parent / "acquisition_manifest.json"

    return original, staged, manifest, event


@pytest.mark.parametrize("transfer_event", [False, True])
def test_recovers_interrupted_ingestion(
    tmp_path,
    transfer_event,
):
    original, staged, manifest, event = prepare_staged_archive(
        tmp_path,
        transfer_event=transfer_event,
    )

    result = finalise_staged_acquisition(
        original,
        staged,
        "0289",
        manifest_path=manifest,
    )

    assert result == manifest
    assert staged.exists()
    assert not pending_acquisition_path(original).exists()
    assert not pending_acquisition_path(staged).exists()

    saved = json.loads(manifest.read_text(encoding="utf-8"))
    record = saved["archives"][0]

    assert record["verification_status"] == "verified"
    assert record["source_url"] == event["source_url"]
    assert record["acquired_at"] == event["acquired_at"]
    assert record["sha256"] == event["sha256"]


def test_recovery_rejects_changed_staged_zip(tmp_path):
    original, staged, manifest, event = prepare_staged_archive(
        tmp_path
    )

    with ZipFile(staged, "w") as archive:
        archive.writestr(
            "UI_files/catlist.ini",
            ";; CATLIST.ini 0.289 / 21-Aug-26 / MAME 0.289 ;;\n"
            "[Arcade: Maze / Collect]\npuckman\n"
            "pacman\n",
        )

    with pytest.raises(ValueError, match="SHA-256"):
        finalise_staged_acquisition(
            original,
            staged,
            "0289",
            manifest_path=manifest,
        )

    assert pending_acquisition_path(original).exists()
    assert not manifest.exists()


def test_recovery_rejects_competing_pending_events(tmp_path):
    original, staged, manifest, event = prepare_staged_archive(
        tmp_path
    )

    pending_acquisition_path(staged).write_text(
        pending_acquisition_path(original).read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="both locations"):
        finalise_staged_acquisition(
            original,
            staged,
            "0289",
            manifest_path=manifest,
        )

    assert pending_acquisition_path(original).exists()
    assert pending_acquisition_path(staged).exists()
    assert not manifest.exists()


def test_no_pending_event_does_not_invent_download(tmp_path):
    original, staged, manifest, event = prepare_staged_archive(
        tmp_path
    )

    pending_acquisition_path(original).unlink()

    result = finalise_staged_acquisition(
        original,
        staged,
        "0289",
        manifest_path=manifest,
    )

    assert result is None
    assert staged.exists()
    assert not manifest.exists()
