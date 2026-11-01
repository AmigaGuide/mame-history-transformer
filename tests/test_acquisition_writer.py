import json
from zipfile import ZipFile

import pytest

from mht.provenance.acquisition import (
    save_acquisition_manifest,
)


def make_mame_archive(path, version="289"):
    with ZipFile(path, "w") as archive:
        archive.writestr(
            f"mame{version}.xml",
            f'<mame build="0.{version} (mame0{version})" '
            f'mameconfig="10"/>',
        )


def test_writer_creates_valid_manifest(tmp_path):
    directory = tmp_path / "archives"
    directory.mkdir()

    make_mame_archive(directory / "mame0289lx.zip")

    destination = tmp_path / "acquisition_manifest.json"

    result = save_acquisition_manifest(
        "0289",
        archive_directory=directory,
        manifest_path=destination,
    )

    assert result == destination
    assert destination.is_file()

    manifest = json.loads(
        destination.read_text(encoding="utf-8")
    )

    assert manifest["release"] == "0289"
    assert len(manifest["archives"]) == 1
    assert (
        manifest["archives"][0]["verification_status"]
        == "verified"
    )


def test_writer_preserves_existing_acquisition_details(tmp_path):
    directory = tmp_path / "archives"
    directory.mkdir()

    make_mame_archive(directory / "mame0289lx.zip")

    destination = tmp_path / "acquisition_manifest.json"

    save_acquisition_manifest(
        "0289",
        archive_directory=directory,
        manifest_path=destination,
    )

    manifest = json.loads(
        destination.read_text(encoding="utf-8")
    )

    manifest["archives"][0]["source_url"] = (
        "https://example.com/original.zip"
    )
    manifest["archives"][0]["acquired_at"] = (
        "2026-10-31T20:00:00Z"
    )

    destination.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    save_acquisition_manifest(
        "0289",
        archive_directory=directory,
        manifest_path=destination,
    )

    updated = json.loads(
        destination.read_text(encoding="utf-8")
    )

    archive = updated["archives"][0]

    assert archive["source_url"] == (
        "https://example.com/original.zip"
    )
    assert archive["acquired_at"] == (
        "2026-10-31T20:00:00Z"
    )


def test_writer_rejects_invalid_archive_without_overwrite(
    tmp_path,
):
    directory = tmp_path / "archives"
    directory.mkdir()

    archive = directory / "mame0289lx.zip"
    make_mame_archive(archive)

    destination = tmp_path / "acquisition_manifest.json"

    save_acquisition_manifest(
        "0289",
        archive_directory=directory,
        manifest_path=destination,
    )

    original = destination.read_bytes()

    archive.write_bytes(b"corrupt ZIP")

    with pytest.raises(ValueError, match="verification"):
        save_acquisition_manifest(
            "0289",
            archive_directory=directory,
            manifest_path=destination,
        )

    assert destination.read_bytes() == original


def test_writer_rejects_empty_release(tmp_path):
    directory = tmp_path / "archives"
    directory.mkdir()

    destination = tmp_path / "acquisition_manifest.json"

    with pytest.raises(ValueError, match="No archives"):
        save_acquisition_manifest(
            "0289",
            archive_directory=directory,
            manifest_path=destination,
        )

    assert not destination.exists()


def test_writer_drops_old_acquisition_details_after_replacement(
    tmp_path,
):
    directory = tmp_path / "archives"
    directory.mkdir()

    archive = directory / "mame0289lx.zip"
    make_mame_archive(archive)

    destination = tmp_path / "acquisition_manifest.json"

    save_acquisition_manifest(
        "0289",
        archive_directory=directory,
        manifest_path=destination,
    )

    manifest = json.loads(
        destination.read_text(encoding="utf-8")
    )

    old_hash = manifest["archives"][0]["sha256"]

    manifest["archives"][0]["source_url"] = (
        "https://example.com/old-source.zip"
    )
    manifest["archives"][0]["acquired_at"] = (
        "2026-10-31T20:00:00Z"
    )

    destination.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    # Replace the ZIP with a different but valid archive.
    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr(
            "mame0289.xml",
            '<mame build="0.289 (mame0289)" '
            'mameconfig="10"><machine name="puckman"/>'
            '</mame>',
        )

    save_acquisition_manifest(
        "0289",
        archive_directory=directory,
        manifest_path=destination,
    )

    updated = json.loads(
        destination.read_text(encoding="utf-8")
    )

    record = updated["archives"][0]

    assert record["verification_status"] == "verified"
    assert record["sha256"] != old_hash
    assert record["source_url"] is None
    assert record["acquired_at"] is None


from mht.provenance.acquisition import build_acquisition_event


def test_writer_records_matching_download_event(tmp_path):
    directory = tmp_path / "archives"
    directory.mkdir()

    archive = directory / "mame0289lx.zip"
    make_mame_archive(archive)

    destination = tmp_path / "acquisition_manifest.json"

    event = build_acquisition_event(
        archive,
        "https://example.com/mame0289lx.zip",
        "0289",
        acquired_at="2026-11-01T14:00:00Z",
    )

    save_acquisition_manifest(
        "0289",
        archive_directory=directory,
        manifest_path=destination,
        acquisition_event=event,
    )

    manifest = json.loads(
        destination.read_text(encoding="utf-8")
    )

    record = manifest["archives"][0]

    assert record["verification_status"] == "verified"
    assert record["source_url"] == event["source_url"]
    assert record["acquired_at"] == event["acquired_at"]
    assert record["sha256"] == event["sha256"]


def test_writer_rejects_invalid_event_without_overwriting(
    tmp_path,
):
    directory = tmp_path / "archives"
    directory.mkdir()

    archive = directory / "mame0289lx.zip"
    make_mame_archive(archive)

    destination = tmp_path / "acquisition_manifest.json"

    save_acquisition_manifest(
        "0289",
        archive_directory=directory,
        manifest_path=destination,
    )

    original = destination.read_bytes()

    event = build_acquisition_event(
        archive,
        "https://example.com/mame0289lx.zip",
        "0289",
        acquired_at="2026-11-01T14:00:00Z",
    )

    event["sha256"] = "incorrect-hash"

    with pytest.raises(ValueError, match="SHA-256"):
        save_acquisition_manifest(
            "0289",
            archive_directory=directory,
            manifest_path=destination,
            acquisition_event=event,
        )

    assert destination.read_bytes() == original
