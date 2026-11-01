from zipfile import ZipFile

import pytest

import mht.provenance.fetch as fetch


@pytest.mark.parametrize(
    "downloader,filename",
    [
        (fetch.mame_download, "mame0289lx.zip"),
        (fetch.gh_download, "history289.zip"),
    ],
)
def test_downloader_uses_verified_helper(
    monkeypatch,
    tmp_path,
    downloader,
    filename,
):
    destination = tmp_path / filename
    calls = []

    def fake_verified(url, dest, *, debug=False):
        calls.append((url, dest, debug))
        return {
            "ok": True,
            "path": dest.as_posix(),
            "note": "downloaded and verified",
        }

    monkeypatch.setattr(
        fetch,
        "_download_verified_archive",
        fake_verified,
    )

    result = downloader(
        "https://example.com/archive.zip",
        destination,
        debug=True,
    )

    assert result["ok"] is True
    assert len(calls) == 1
    assert calls[0][1] == destination
    assert calls[0][2] is True


@pytest.mark.parametrize(
    "downloader,filename",
    [
        (fetch.mame_download, "mame0289lx.zip"),
        (fetch.gh_download, "history289.zip"),
    ],
)
def test_existing_archive_is_not_redownloaded(
    monkeypatch,
    tmp_path,
    downloader,
    filename,
):
    destination = tmp_path / filename

    with ZipFile(destination, "w") as archive:
        if filename.startswith("mame"):
            archive.writestr(
                "mame0289.xml",
                '<mame build="0.289 (mame0289)" mameconfig="10"/>',
            )
        else:
            archive.writestr(
                "history/history.xml",
                '<history version="2.89" date="2026-08-07"/>',
            )

    original_bytes = destination.read_bytes()

    def unexpected_download(*args, **kwargs):
        raise AssertionError("Downloader must not be called")

    monkeypatch.setattr(
        fetch,
        "_download_verified_archive",
        unexpected_download,
    )

    result = downloader(
        "https://example.com/archive.zip",
        destination,
    )

    assert result["ok"] is True
    assert result["reason"] == "exists"
    assert destination.read_bytes() == original_bytes


@pytest.mark.parametrize(
    "downloader,filename",
    [
        (fetch.mame_download, "mame0289lx.zip"),
        (fetch.gh_download, "history289.zip"),
    ],
)
def test_overwrite_uses_verified_helper(
    monkeypatch,
    tmp_path,
    downloader,
    filename,
):
    destination = tmp_path / filename
    destination.write_bytes(b"existing archive")

    calls = []

    def fake_verified(url, dest, *, debug=False):
        calls.append(dest)
        return {"ok": True}

    monkeypatch.setattr(
        fetch,
        "_download_verified_archive",
        fake_verified,
    )

    result = downloader(
        "https://example.com/archive.zip",
        destination,
        overwrite=True,
    )

    assert result["ok"] is True
    assert calls == [destination]


@pytest.mark.parametrize(
    "downloader,filename",
    [
        (fetch.mame_download, "mame0289lx.zip"),
        (fetch.gh_download, "history289.zip"),
    ],
)
def test_invalid_existing_archive_is_rejected(
    monkeypatch,
    tmp_path,
    downloader,
    filename,
):
    destination = tmp_path / filename
    destination.write_bytes(b"incomplete ZIP")

    def unexpected_download(*args, **kwargs):
        raise AssertionError("Unexpected download")

    monkeypatch.setattr(
        fetch,
        "_download_verified_archive",
        unexpected_download,
    )

    result = downloader(
        "https://example.com/archive.zip",
        destination,
    )

    assert result["ok"] is False
    assert result["reason"] == "invalid_existing_archive"
    assert destination.read_bytes() == b"incomplete ZIP"
    assert "overwrite" in result["note"]
