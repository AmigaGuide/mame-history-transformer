import json

import pytest

from mht.provenance.acquisition import (
    build_acquisition_event,
    load_pending_acquisition_event,
    pending_acquisition_path,
    save_pending_acquisition_event,
)


def make_archive_and_event(tmp_path):
    archive = tmp_path / "history289.zip"
    archive.write_bytes(b"example archive contents")

    event = build_acquisition_event(
        archive,
        "https://example.com/history289.zip",
        "0289",
        acquired_at="2026-11-01T14:00:00Z",
    )

    return archive, event


def test_pending_event_round_trip(tmp_path):
    archive, event = make_archive_and_event(tmp_path)

    destination = save_pending_acquisition_event(
        archive, event
    )

    assert destination == pending_acquisition_path(archive)
    assert destination.is_file()
    assert load_pending_acquisition_event(archive) == event


def test_missing_pending_event_returns_none(tmp_path):
    archive, event = make_archive_and_event(tmp_path)

    assert load_pending_acquisition_event(archive) is None


def test_stale_pending_event_is_rejected(tmp_path):
    archive, event = make_archive_and_event(tmp_path)

    save_pending_acquisition_event(archive, event)

    archive.write_bytes(b"replacement archive contents")

    with pytest.raises(ValueError, match="SHA-256"):
        load_pending_acquisition_event(archive)


def test_wrong_filename_is_rejected(tmp_path):
    archive, event = make_archive_and_event(tmp_path)

    event["filename"] = "history288.zip"

    with pytest.raises(ValueError, match="filename mismatch"):
        save_pending_acquisition_event(archive, event)

    assert not pending_acquisition_path(archive).exists()


def test_invalid_pending_json_is_rejected(tmp_path):
    archive, event = make_archive_and_event(tmp_path)

    pending_acquisition_path(archive).write_text(
        json.dumps(["not", "an", "event"]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not a JSON object"):
        load_pending_acquisition_event(archive)


def test_pending_event_survives_repeated_reads(tmp_path):
    archive, event = make_archive_and_event(tmp_path)

    save_pending_acquisition_event(archive, event)

    first = load_pending_acquisition_event(archive)
    second = load_pending_acquisition_event(archive)

    assert first == second == event
    assert pending_acquisition_path(archive).exists()
