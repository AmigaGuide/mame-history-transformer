import shutil

import pytest

from mht.provenance.acquisition import (
    build_acquisition_event,
    load_pending_acquisition_event,
    pending_acquisition_path,
    save_pending_acquisition_event,
    transfer_pending_acquisition_event,
)


def prepare_transfer(tmp_path):
    incoming = tmp_path / "incoming"
    staged = tmp_path / "releases" / "0289" / "archives"

    incoming.mkdir(parents=True)
    staged.mkdir(parents=True)

    original = incoming / "history289.zip"
    destination = staged / original.name

    original.write_bytes(b"example archive contents")

    event = build_acquisition_event(
        original,
        "https://example.com/history289.zip",
        "0289",
        acquired_at="2026-11-01T14:00:00Z",
    )

    save_pending_acquisition_event(original, event)

    # Simulate ingestion moving the ZIP but not its event.
    shutil.move(str(original), str(destination))

    return original, destination, event


def test_pending_event_follows_staged_zip(tmp_path):
    original, destination, event = prepare_transfer(tmp_path)

    result = transfer_pending_acquisition_event(
        original,
        destination,
    )

    assert result == pending_acquisition_path(destination)
    assert not pending_acquisition_path(original).exists()
    assert load_pending_acquisition_event(destination) == event


def test_missing_event_does_not_fabricate_provenance(tmp_path):
    original, destination, event = prepare_transfer(tmp_path)

    pending_acquisition_path(original).unlink()

    result = transfer_pending_acquisition_event(
        original,
        destination,
    )

    assert result is None
    assert not pending_acquisition_path(destination).exists()


def test_changed_staged_zip_rejects_event(tmp_path):
    original, destination, event = prepare_transfer(tmp_path)

    destination.write_bytes(b"different contents")

    with pytest.raises(ValueError, match="SHA-256"):
        transfer_pending_acquisition_event(
            original,
            destination,
        )

    assert pending_acquisition_path(original).exists()
    assert not pending_acquisition_path(destination).exists()


def test_existing_destination_event_is_preserved(tmp_path):
    original, destination, event = prepare_transfer(tmp_path)

    pending_acquisition_path(destination).write_text(
        "existing pending event",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="already contains"):
        transfer_pending_acquisition_event(
            original,
            destination,
        )

    assert pending_acquisition_path(original).exists()
    assert (
        pending_acquisition_path(destination).read_text(
            encoding="utf-8"
        )
        == "existing pending event"
    )
