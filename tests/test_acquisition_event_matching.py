import pytest

from mht.provenance.acquisition import apply_acquisition_event


def make_manifest():
    return {
        "schema_id": "mht.acquisition.manifest",
        "schema_version": "1.0.0",
        "release": "0289",
        "archives": [
            {
                "filename": "pS_CatVer_289.zip",
                "source_type": "snaps",
                "sha256": "abc123",
                "verification_status": "verified",
                "source_url": None,
                "acquired_at": None,
            }
        ],
    }


def make_event():
    return {
        "event_type": "download",
        "source_type": "snaps",
        "filename": "pS_CatVer_289.zip",
        "release": "0289",
        "source_url": "https://example.com/catver.zip",
        "acquired_at": "2026-11-01T13:00:00Z",
        "sha256": "abc123",
    }


def test_matching_event_updates_manifest():
    manifest = make_manifest()
    event = make_event()

    updated = apply_acquisition_event(manifest, event)

    record = updated["archives"][0]

    assert record["source_url"] == event["source_url"]
    assert record["acquired_at"] == event["acquired_at"]

    # The original must not change.
    assert manifest["archives"][0]["source_url"] is None


def test_wrong_hash_is_rejected():
    event = make_event()
    event["sha256"] = "different"

    with pytest.raises(ValueError, match="SHA-256"):
        apply_acquisition_event(make_manifest(), event)


def test_wrong_release_is_rejected():
    event = make_event()
    event["release"] = "0288"

    with pytest.raises(ValueError, match="release mismatch"):
        apply_acquisition_event(make_manifest(), event)


def test_wrong_provider_is_rejected():
    event = make_event()
    event["source_type"] = "gaming_history"

    with pytest.raises(ValueError, match="provider mismatch"):
        apply_acquisition_event(make_manifest(), event)


def test_unverified_archive_is_rejected():
    manifest = make_manifest()
    manifest["archives"][0]["verification_status"] = "unverified"

    with pytest.raises(ValueError, match="unverified"):
        apply_acquisition_event(manifest, make_event())


def test_unknown_archive_is_rejected():
    event = make_event()
    event["filename"] = "pS_CatVer_288.zip"

    with pytest.raises(ValueError, match="exactly one"):
        apply_acquisition_event(make_manifest(), event)


def test_duplicate_archive_records_are_rejected():
    manifest = make_manifest()
    manifest["archives"].append(
        dict(manifest["archives"][0])
    )

    with pytest.raises(ValueError, match="exactly one"):
        apply_acquisition_event(manifest, make_event())
