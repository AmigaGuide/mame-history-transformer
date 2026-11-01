from zipfile import ZipFile

import mht.provenance.fetch as fetch
from mht.provenance.acquisition import (
    build_acquisition_event,
    pending_acquisition_path,
    save_pending_acquisition_event,
)


def test_valid_existing_mame_archive(tmp_path):
    archive = tmp_path / "mame0289lx.zip"

    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr(
            "mame0289.xml",
            '<mame build="0.289 (mame0289)" mameconfig="10"/>',
        )

    result = fetch._verify_existing_download(archive)

    assert result["ok"] is True
    assert result["reason"] == "exists"
    assert result["integrity"]["status"] == "passed"


def test_existing_archive_with_wrong_release(tmp_path):
    archive = tmp_path / "history289.zip"

    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr(
            "history/history.xml",
            '<history version="2.88" date="2026-06-10"/>',
        )

    original_bytes = archive.read_bytes()

    result = fetch._verify_existing_download(archive)

    assert result["ok"] is False
    assert result["reason"] == "invalid_existing_archive"
    assert archive.read_bytes() == original_bytes


def test_corrupt_existing_archive_is_not_accepted(tmp_path):
    archive = tmp_path / "mame0289lx.zip"
    archive.write_bytes(b"incomplete download")

    result = fetch._verify_existing_download(archive)

    assert result["ok"] is False
    assert result["reason"] == "invalid_existing_archive"
    assert archive.read_bytes() == b"incomplete download"


def test_existing_archive_without_pending_event(tmp_path):
    archive = tmp_path / "mame0289lx.zip"

    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr(
            "mame0289.xml",
            '<mame build="0.289 (mame0289)" mameconfig="10"/>',
        )

    result = fetch._verify_existing_download(archive)

    assert result["ok"] is True
    assert result["pending_acquisition"] is None


def test_existing_archive_with_matching_pending_event(tmp_path):
    archive = tmp_path / "mame0289lx.zip"

    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr(
            "mame0289.xml",
            '<mame build="0.289 (mame0289)" mameconfig="10"/>',
        )

    event = build_acquisition_event(
        archive,
        "https://example.com/mame0289lx.zip",
        "0289",
        acquired_at="2026-11-01T14:00:00Z",
    )

    save_pending_acquisition_event(archive, event)

    result = fetch._verify_existing_download(archive)

    assert result["ok"] is True
    assert result["pending_acquisition"] == event


def test_existing_archive_with_stale_pending_event(tmp_path):
    archive = tmp_path / "mame0289lx.zip"

    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr(
            "mame0289.xml",
            '<mame build="0.289 (mame0289)" mameconfig="10"/>',
        )

    event = build_acquisition_event(
        archive,
        "https://example.com/mame0289lx.zip",
        "0289",
        acquired_at="2026-11-01T14:00:00Z",
    )

    save_pending_acquisition_event(archive, event)

    # Simulate an archive being replaced without updating
    # its corresponding acquisition record.
    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr(
            "mame0289.xml",
            '<mame build="0.289 (mame0289)" mameconfig="10">'
            '<machine name="puckman"/>'
            '</mame>',
        )

    result = fetch._verify_existing_download(archive)

    assert result["ok"] is False
    assert result["reason"] == "invalid_pending_acquisition"
    assert "SHA-256" in result["error"]

    # Neither file should be removed or rewritten.
    assert pending_acquisition_path(archive).exists()
    assert archive.exists()
