from zipfile import ZipFile

import mht.provenance.fetch as fetch
from mht.provenance.acquisition import (
    load_pending_acquisition_event,
    pending_acquisition_path,
)
from mht.provenance.acquisition import (
    build_acquisition_event,
    save_pending_acquisition_event,
)


def test_verified_mame_download(monkeypatch, tmp_path):
    destination = tmp_path / "mame0289lx.zip"

    def fake_download(url, path, **kwargs):
        with ZipFile(path, "w") as archive:
            archive.writestr(
                "mame0289.xml",
                '<mame build="0.289 (mame0289)" mameconfig="10"/>',
            )
        return {"ok": True}

    monkeypatch.setattr(fetch, "download_zip", fake_download)

    result = fetch._download_verified_archive(
        "https://example.com/mame0289lx.zip",
        destination,
    )

    assert result["ok"] is True
    assert destination.exists()

    event = load_pending_acquisition_event(destination)

    assert event is not None
    assert event["source_type"] == "mame"
    assert event["release"] == "0289"
    assert event["sha256"] == result["sha256"]


def test_verified_history_download(monkeypatch, tmp_path):
    destination = tmp_path / "history289.zip"

    def fake_download(url, path, **kwargs):
        with ZipFile(path, "w") as archive:
            archive.writestr(
                "history/history.xml",
                '<history version="2.89" date="2026-08-07"/>',
            )
        return {"ok": True}

    monkeypatch.setattr(fetch, "download_zip", fake_download)

    result = fetch._download_verified_archive(
        "https://example.com/history289.zip",
        destination,
    )

    assert result["ok"] is True

    event = load_pending_acquisition_event(destination)

    assert event["source_type"] == "gaming_history"
    assert event["release"] == "0289"
    assert event["source_url"] == (
        "https://example.com/history289.zip"
    )


def test_failed_download_preserves_existing_archive(
    monkeypatch,
    tmp_path,
):
    destination = tmp_path / "mame0289lx.zip"
    destination.write_bytes(b"existing archive")

    def fake_download(url, path, **kwargs):
        path.write_bytes(b"partial download")
        return {"ok": False, "error": "Transfer interrupted"}

    monkeypatch.setattr(fetch, "download_zip", fake_download)

    result = fetch._download_verified_archive(
        "https://example.com/mame0289lx.zip",
        destination,
    )

    assert result["ok"] is False
    assert destination.read_bytes() == b"existing archive"
    assert not pending_acquisition_path(destination).exists()


def test_wrong_embedded_release_is_rejected(
    monkeypatch,
    tmp_path,
):
    destination = tmp_path / "history289.zip"

    def fake_download(url, path, **kwargs):
        with ZipFile(path, "w") as archive:
            archive.writestr(
                "history/history.xml",
                '<history version="2.88" date="2026-06-10"/>',
            )
        return {"ok": True}

    monkeypatch.setattr(fetch, "download_zip", fake_download)

    result = fetch._download_verified_archive(
        "https://example.com/history289.zip",
        destination,
    )

    assert result["ok"] is False
    assert not destination.exists()
    assert not pending_acquisition_path(destination).exists()


def test_successful_replacement_updates_acquisition_event(
    monkeypatch,
    tmp_path,
):
    destination = tmp_path / "mame0289lx.zip"

    with ZipFile(destination, "w") as archive:
        archive.writestr(
            "mame0289.xml",
            '<mame build="0.289 (mame0289)" mameconfig="10"/>',
        )

    original_event = build_acquisition_event(
        destination,
        "https://example.com/old-download.zip",
        "0289",
        acquired_at="2026-10-01T12:00:00Z",
    )
    save_pending_acquisition_event(destination, original_event)

    def fake_download(url, path, **kwargs):
        with ZipFile(path, "w") as archive:
            archive.writestr(
                "mame0289.xml",
                '<mame build="0.289 (mame0289)" mameconfig="10">'
                '<machine name="puckman"/>'
                '</mame>',
            )
        return {"ok": True}

    monkeypatch.setattr(fetch, "download_zip", fake_download)

    result = fetch._download_verified_archive(
        "https://example.com/new-download.zip",
        destination,
    )

    assert result["ok"] is True

    updated_event = load_pending_acquisition_event(destination)

    assert updated_event is not None
    assert updated_event["source_url"] == (
        "https://example.com/new-download.zip"
    )
    assert updated_event["sha256"] == result["sha256"]
    assert updated_event["sha256"] != original_event["sha256"]
    assert updated_event["acquired_at"] != original_event["acquired_at"]

    with ZipFile(destination) as archive:
        xml = archive.read("mame0289.xml")

    assert b'puckman' in xml


def test_rejected_replacement_preserves_archive_and_event(
    monkeypatch,
    tmp_path,
):
    destination = tmp_path / "history289.zip"

    with ZipFile(destination, "w") as archive:
        archive.writestr(
            "history/history.xml",
            '<history version="2.89" date="2026-08-07"/>',
        )

    original_bytes = destination.read_bytes()

    original_event = build_acquisition_event(
        destination,
        "https://example.com/old-history.zip",
        "0289",
        acquired_at="2026-10-01T12:00:00Z",
    )
    save_pending_acquisition_event(destination, original_event)

    def fake_download(url, path, **kwargs):
        with ZipFile(path, "w") as archive:
            archive.writestr(
                "history/history.xml",
                '<history version="2.88" date="2026-06-10"/>',
            )
        return {"ok": True}

    monkeypatch.setattr(fetch, "download_zip", fake_download)

    result = fetch._download_verified_archive(
        "https://example.com/new-history.zip",
        destination,
    )

    assert result["ok"] is False
    assert destination.read_bytes() == original_bytes

    retained_event = load_pending_acquisition_event(destination)

    assert retained_event == original_event
