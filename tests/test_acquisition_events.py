import pytest

from mht.provenance.acquisition import (
    build_acquisition_event,
)
from mht.utils.io import sha256_file


def test_download_event_records_archive_identity(tmp_path):
    archive = tmp_path / "pS_CatVer_289.zip"
    archive.write_bytes(b"example archive bytes")

    url = (
        "https://www.progettosnaps.net/download/"
        "?tipo=catver&file=pS_CatVer_289.zip"
    )

    result = build_acquisition_event(
        archive,
        url,
        "0289",
        acquired_at="2026-10-31T20:27:18Z",
    )

    assert result["event_type"] == "download"
    assert result["source_type"] == "snaps"
    assert result["release"] == "0289"
    assert result["source_url"] == url
    assert result["acquired_at"] == "2026-10-31T20:27:18Z"
    assert result["size_bytes"] == archive.stat().st_size
    assert result["sha256"] == sha256_file(archive)


@pytest.mark.parametrize(
    ("filename", "provider"),
    [
        ("mame0289lx.zip", "mame"),
        ("history289.zip", "gaming_history"),
        ("pS_CatVer_289.zip", "snaps"),
    ],
)
def test_event_supports_all_providers(
    tmp_path,
    filename,
    provider,
):
    archive = tmp_path / filename
    archive.write_bytes(b"example contents")

    result = build_acquisition_event(
        archive,
        "https://example.com/archive.zip",
        "0289",
        acquired_at="2026-11-01T12:00:00Z",
    )

    assert result["source_type"] == provider


def test_event_rejects_release_mismatch(tmp_path):
    archive = tmp_path / "history288.zip"
    archive.write_bytes(b"example contents")

    with pytest.raises(ValueError, match="does not match"):
        build_acquisition_event(
            archive,
            "https://example.com/history288.zip",
            "0289",
        )


def test_event_rejects_unknown_provider(tmp_path):
    archive = tmp_path / "unknown.zip"
    archive.write_bytes(b"example contents")

    with pytest.raises(ValueError, match="Unrecognised"):
        build_acquisition_event(
            archive,
            "https://example.com/unknown.zip",
            "0289",
        )


def test_event_rejects_non_https_url(tmp_path):
    archive = tmp_path / "mame0289lx.zip"
    archive.write_bytes(b"example contents")

    with pytest.raises(ValueError, match="HTTPS"):
        build_acquisition_event(
            archive,
            "http://example.com/mame0289lx.zip",
            "0289",
        )
