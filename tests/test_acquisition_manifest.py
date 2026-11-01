from mht.provenance.acquisition import (
    build_acquisition_manifest,
)


def make_record(sha256="abc123"):
    return {
        "filename": "pS_CatVer_289.zip",
        "source_type": "snaps",
        "release": "0289",
        "sha256": sha256,
        "source_url": None,
        "acquired_at": None,
        "verification_status": "verified",
    }


def test_manifest_contains_release_and_archive():
    result = build_acquisition_manifest(
        "0289",
        [make_record()],
    )

    assert result["schema_id"] == "mht.acquisition.manifest"
    assert result["schema_version"] == "1.0.0"
    assert result["release"] == "0289"
    assert len(result["archives"]) == 1


def test_existing_acquisition_details_are_preserved():
    previous = build_acquisition_manifest(
        "0289",
        [make_record()],
    )

    previous["archives"][0]["source_url"] = (
        "https://www.progettosnaps.net/download/"
    )
    previous["archives"][0]["acquired_at"] = (
        "2026-10-31T20:00:00Z"
    )

    result = build_acquisition_manifest(
        "0289",
        [make_record()],
        previous=previous,
    )

    archive = result["archives"][0]

    assert archive["source_url"] == (
        "https://www.progettosnaps.net/download/"
    )
    assert archive["acquired_at"] == (
        "2026-10-31T20:00:00Z"
    )


def test_changed_hash_does_not_inherit_acquisition():
    previous = build_acquisition_manifest(
        "0289",
        [make_record("oldhash")],
    )

    previous["archives"][0]["source_url"] = (
        "https://example.com/old-archive.zip"
    )
    previous["archives"][0]["acquired_at"] = (
        "2026-10-31T20:00:00Z"
    )

    result = build_acquisition_manifest(
        "0289",
        [make_record("newhash")],
        previous=previous,
    )

    archive = result["archives"][0]

    assert archive["source_url"] is None
    assert archive["acquired_at"] is None


def test_manifest_rejects_different_release():
    previous = build_acquisition_manifest(
        "0288",
        [make_record()],
    )

    try:
        build_acquisition_manifest(
            "0289",
            [make_record()],
            previous=previous,
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Expected a release mismatch to be rejected"
        )
