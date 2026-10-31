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
