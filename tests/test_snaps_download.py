from zipfile import ZipFile

from mht.provenance import fetch
from mht.provenance.snaps_sources import SnapsSource


def source():
    return SnapsSource(
        release="0289",
        package_type="catver",
        filename="pS_CatVer_289.zip",
        url="https://www.progettosnaps.net/download/",
    )


def test_valid_download_is_staged(monkeypatch, tmp_path):
    destination = tmp_path / "incoming"

    def fake_download(url, path, **kwargs):
        with ZipFile(path, "w") as archive:
            archive.writestr(
                "CatVer/catlist.ini",
                "[Arcade: Maze / Collect]\npuckman\n",
            )
        return {"ok": True}

    monkeypatch.setattr(fetch, "download_zip", fake_download)

    result = fetch.snaps_download(
        source(),
        destination_dir=destination,
    )

    assert result["ok"] is True
    assert (destination / source().filename).exists()
    assert result["provenance"]["classifications"] == 1


def test_invalid_download_does_not_replace_existing(
    monkeypatch,
    tmp_path,
):
    destination = tmp_path / "incoming"
    destination.mkdir()

    existing = destination / source().filename
    existing.write_bytes(b"previous archive")

    def fake_download(url, path, **kwargs):
        path.write_bytes(b"not a valid ZIP")
        return {"ok": True}

    monkeypatch.setattr(fetch, "download_zip", fake_download)

    result = fetch.snaps_download(
        source(),
        destination_dir=destination,
        overwrite=True,
    )

    assert result["ok"] is False
    assert existing.read_bytes() == b"previous archive"


def test_existing_archive_is_not_overwritten(
    monkeypatch,
    tmp_path,
):
    destination = tmp_path / "incoming"
    destination.mkdir()

    existing = destination / source().filename
    with ZipFile(existing, "w") as archive:
        archive.writestr(
            "CatVer/catlist.ini",
            "[Arcade: Maze / Collect]\npuckman\n",
        )

    original = existing.read_bytes()

    def unexpected_download(*args, **kwargs):
        raise AssertionError("Unexpected network download")

    monkeypatch.setattr(
        fetch,
        "download_zip",
        unexpected_download,
    )

    result = fetch.snaps_download(
        source(),
        destination_dir=destination,
    )

    assert result["ok"] is True
    assert result["reason"] == "exists"
    assert existing.read_bytes() == original
    assert result["provenance"]["classifications"] == 1


def test_invalid_existing_archive_is_not_silently_accepted(
    monkeypatch,
    tmp_path,
):
    destination = tmp_path / "incoming"
    destination.mkdir()

    existing = destination / source().filename
    existing.write_bytes(b"corrupt ZIP contents")

    def unexpected_download(*args, **kwargs):
        raise AssertionError("Unexpected network download")

    monkeypatch.setattr(
        fetch,
        "download_zip",
        unexpected_download,
    )

    result = fetch.snaps_download(
        source(),
        destination_dir=destination,
    )

    assert result["ok"] is False
    assert result["reason"] == "invalid_existing_archive"
    assert existing.read_bytes() == b"corrupt ZIP contents"


from mht.provenance.acquisition import (
    load_pending_acquisition_event,
    pending_acquisition_path,
)


def test_successful_download_records_pending_acquisition(
    monkeypatch,
    tmp_path,
):
    destination = tmp_path / "incoming"

    def fake_download(url, path, **kwargs):
        with ZipFile(path, "w") as archive:
            archive.writestr(
                "UI_files/catlist.ini",
                ";; CATLIST.ini 0.289 / 21-Aug-26 / MAME 0.289 ;;\n"
                "[Arcade: Maze / Collect]\npuckman\n",
            )
        return {"ok": True}

    monkeypatch.setattr(fetch, "download_zip", fake_download)

    result = fetch.snaps_download(
        source(),
        destination_dir=destination,
    )

    assert result["ok"] is True

    archive = destination / source().filename
    event = load_pending_acquisition_event(archive)

    assert event is not None
    assert event["event_type"] == "download"
    assert event["source_type"] == "snaps"
    assert event["release"] == "0289"
    assert event["source_url"] == source().url
    assert event["sha256"] == result["sha256"]
    assert result["acquisition_event"] == event


def test_failed_download_creates_no_pending_event(
    monkeypatch,
    tmp_path,
):
    destination = tmp_path / "incoming"

    def fake_download(url, path, **kwargs):
        return {
            "ok": False,
            "error": "Simulated transfer failure",
        }

    monkeypatch.setattr(fetch, "download_zip", fake_download)

    result = fetch.snaps_download(
        source(),
        destination_dir=destination,
    )

    archive = destination / source().filename

    assert result["ok"] is False
    assert not archive.exists()
    assert not pending_acquisition_path(archive).exists()


def test_reusing_existing_archive_does_not_create_event(
    monkeypatch,
    tmp_path,
):
    destination = tmp_path / "incoming"
    destination.mkdir()

    archive = destination / source().filename

    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr(
            "UI_files/catlist.ini",
            "[Arcade: Maze / Collect]\npuckman\n",
        )

    def unexpected_download(*args, **kwargs):
        raise AssertionError("Unexpected network download")

    monkeypatch.setattr(
        fetch,
        "download_zip",
        unexpected_download,
    )

    result = fetch.snaps_download(
        source(),
        destination_dir=destination,
    )

    assert result["ok"] is True
    assert result["reason"] == "exists"
    assert not pending_acquisition_path(archive).exists()
    assert "acquisition_event" not in result
