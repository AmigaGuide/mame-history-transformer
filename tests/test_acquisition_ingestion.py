import json
from zipfile import ZipFile

import pytest

from mht.provenance import acquisition, archives
from mht.provenance.acquisition import (
    build_acquisition_event,
    pending_acquisition_path,
    save_pending_acquisition_event,
)


@pytest.fixture
def staging_environment(monkeypatch, tmp_path):
    incoming = tmp_path / "incoming"
    releases = tmp_path / "releases"

    incoming.mkdir()

    # Redirect both staging and manifest auditing so that
    # no real release archive directories are touched.
    monkeypatch.setattr(
        archives,
        "archives_dir",
        lambda release: releases / release / "archives",
    )
    monkeypatch.setattr(
        acquisition,
        "archives_dir",
        lambda release: releases / release / "archives",
    )

    # Keep directory creation inside our temporary tree.
    monkeypatch.setattr(
        archives,
        "ensure_release_dirs",
        lambda release: (
            releases / release / "archives"
        ).mkdir(parents=True, exist_ok=True),
    )

    return incoming, releases


def make_archive(path):
    with ZipFile(path, "w") as archive:
        if path.name.startswith("mame"):
            archive.writestr(
                "mame0289.xml",
                '<mame build="0.289 (mame0289)" mameconfig="10"/>',
            )
        else:
            archive.writestr(
                "history/history.xml",
                '<history version="2.89" date="2026-08-07"/>',
            )


@pytest.mark.parametrize(
    "filename,url,provider",
    [
        (
            "mame0289lx.zip",
            "https://example.com/mame0289lx.zip",
            "mame",
        ),
        (
            "history289.zip",
            "https://example.com/history289.zip",
            "gaming_history",
        ),
    ],
)
def test_ingestion_preserves_acquisition_provenance(
    staging_environment,
    filename,
    url,
    provider,
):
    incoming, releases = staging_environment
    source = incoming / filename
    make_archive(source)

    event = build_acquisition_event(
        source,
        url,
        "0289",
        acquired_at="2026-11-01T14:00:00Z",
    )
    save_pending_acquisition_event(source, event)

    results = archives.import_incoming_archives(
        incoming=incoming,
    )

    assert len(results) == 1
    assert results[0]["action"] == "moved"
    assert results[0]["version"] == "0289"

    staged = releases / "0289" / "archives" / filename

    assert staged.exists()
    assert not source.exists()
    assert not pending_acquisition_path(source).exists()
    assert not pending_acquisition_path(staged).exists()

    manifest_path = releases / "0289" / "acquisition_manifest.json"
    assert manifest_path.exists()

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = data["archives"][0]

    assert record["source_type"] == provider
    assert record["verification_status"] == "verified"
    assert record["source_url"] == url
    assert record["acquired_at"] == event["acquired_at"]
    assert record["sha256"] == event["sha256"]


def test_conflicting_archive_preserves_incoming_evidence(
    staging_environment,
):
    incoming, releases = staging_environment

    source = incoming / "history289.zip"
    make_archive(source)

    event = build_acquisition_event(
        source,
        "https://example.com/history289.zip",
        "0289",
        acquired_at="2026-11-01T14:00:00Z",
    )
    save_pending_acquisition_event(source, event)

    staged_directory = releases / "0289" / "archives"
    staged_directory.mkdir(parents=True, exist_ok=True)

    existing = staged_directory / source.name
    existing.write_bytes(b"previous archive contents")

    results = archives.import_incoming_archives(
        incoming=incoming,
    )

    assert len(results) == 1
    assert results[0]["action"] == "skipped"
    assert results[0]["reason"] == "archive_already_staged"

    assert source.exists()
    assert pending_acquisition_path(source).exists()
    assert existing.read_bytes() == b"previous archive contents"

    assert not (
        staged_directory / "history289__dup1.zip"
    ).exists()
    assert not (
        releases / "0289" / "acquisition_manifest.json"
    ).exists()


def test_incoming_zip_is_discovered_only_once(
    staging_environment,
):
    incoming, releases = staging_environment

    source = incoming / "history289.zip"
    make_archive(source)

    event = build_acquisition_event(
        source,
        "https://example.com/history289.zip",
        "0289",
        acquired_at="2026-11-01T14:00:00Z",
    )
    save_pending_acquisition_event(source, event)

    staged_directory = releases / "0289" / "archives"
    staged_directory.mkdir(parents=True, exist_ok=True)

    existing = staged_directory / source.name
    make_archive(existing)

    results = archives.import_incoming_archives(
        incoming=incoming,
    )

    assert len(results) == 1
    assert results[0]["action"] == "skipped"
    assert results[0]["reason"] == "archive_already_staged"

    assert source.exists()
    assert existing.exists()
    assert pending_acquisition_path(source).exists()


@pytest.mark.parametrize(
    "filename,url",
    [
        (
            "mame0289lx.zip",
            "https://example.com/mame0289lx.zip",
        ),
        (
            "history289.zip",
            "https://example.com/history289.zip",
        ),
    ],
)
def test_manifest_failure_preserves_recoverable_acquisition(
    staging_environment,
    monkeypatch,
    filename,
    url,
):
    incoming, releases = staging_environment

    source = incoming / filename
    make_archive(source)

    event = build_acquisition_event(
        source,
        url,
        "0289",
        acquired_at="2026-11-01T14:00:00Z",
    )
    save_pending_acquisition_event(source, event)

    def failed_manifest(*args, **kwargs):
        raise OSError("Simulated manifest write failure")

    # Simulate a failure only during initial ingestion.
    with monkeypatch.context() as patch:
        patch.setattr(
            acquisition,
            "save_acquisition_manifest",
            failed_manifest,
        )

        results = archives.import_incoming_archives(
            incoming=incoming,
        )

    staged = releases / "0289" / "archives" / filename
    manifest = releases / "0289" / "acquisition_manifest.json"

    assert len(results) == 1
    assert results[0]["action"] == "error"
    assert (
        results[0]["reason"]
        == "acquisition_provenance_pending"
    )

    # The ZIP has moved, but its provenance remains available.
    assert staged.exists()
    assert not source.exists()
    assert pending_acquisition_path(staged).exists()
    assert not manifest.exists()

    # Retry using the shared acquisition recovery mechanism.
    recovered = acquisition.finalise_staged_acquisition(
        source,
        staged,
        "0289",
        manifest_path=manifest,
    )

    assert recovered == manifest
    assert manifest.exists()
    assert not pending_acquisition_path(staged).exists()

    data = json.loads(
        manifest.read_text(encoding="utf-8")
    )
    record = data["archives"][0]

    assert record["verification_status"] == "verified"
    assert record["source_url"] == event["source_url"]
    assert record["acquired_at"] == event["acquired_at"]
    assert record["sha256"] == event["sha256"]
