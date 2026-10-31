from argparse import Namespace
from unittest.mock import Mock

from mht import cli
from mht.provenance import fetch


def make_args():
    return Namespace(
        version="0289",
        yes=True,
        overwrite=False,
        debug=False,
    )


def test_snaps_command_downloads_resolved_release(monkeypatch, tmp_path):
    source = Mock()
    source.release = "0289"
    source.package_type = "catver"
    source.filename = "pS_CatVer_289.zip"
    source.url = "https://www.progettosnaps.net/download/"

    monkeypatch.setattr(
        cli,
        "archives_dir",
        lambda version: tmp_path / version / "archives",
    )

    download = Mock(return_value={
        "ok": True,
        "note": "downloaded and validated",
        "path": "data/incoming/pS_CatVer_289.zip",
        "provenance": {
            "catlist_member": "CatVer/catlist.ini",
            "classifications": 49860,
        },
    })

    monkeypatch.setattr(
        fetch, "probe_snaps", lambda *a, **kw: source
    )
    monkeypatch.setattr(fetch, "snaps_download", download)

    assert cli.cmd_fetch_snaps(make_args()) == 0
    download.assert_called_once_with(
        source,
        overwrite=False,
        debug=False,
    )


def test_snaps_command_refuses_missing_release(monkeypatch):
    monkeypatch.setattr(
        fetch, "probe_snaps", lambda *a, **kw: None
    )

    download = Mock()
    monkeypatch.setattr(fetch, "snaps_download", download)

    assert cli.cmd_fetch_snaps(make_args()) == 1
    download.assert_not_called()


from zipfile import ZipFile


def test_snaps_command_reuses_staged_archive(
    monkeypatch,
    tmp_path,
):
    from mht.provenance.snaps_sources import SnapsSource

    source = SnapsSource(
        release="0289",
        package_type="catver",
        filename="pS_CatVer_289.zip",
        url="https://www.progettosnaps.net/download/",
    )

    staged_dir = tmp_path / "0289" / "archives"
    staged_dir.mkdir(parents=True)

    staged = staged_dir / source.filename

    with ZipFile(staged, "w") as archive:
        archive.writestr(
            "CatVer/catlist.ini",
            "[Arcade: Maze / Collect]\npuckman\n",
        )

    monkeypatch.setattr(
        cli,
        "archives_dir",
        lambda version: tmp_path / version / "archives",
    )
    monkeypatch.setattr(
        fetch,
        "probe_snaps",
        lambda *args, **kwargs: source,
    )

    download = Mock()
    monkeypatch.setattr(fetch, "snaps_download", download)

    assert cli.cmd_fetch_snaps(make_args()) == 0
    download.assert_not_called()


def test_snaps_command_rejects_corrupt_staged_archive(
    monkeypatch,
    tmp_path,
):
    from mht.provenance.snaps_sources import SnapsSource

    source = SnapsSource(
        release="0289",
        package_type="catver",
        filename="pS_CatVer_289.zip",
        url="https://www.progettosnaps.net/download/",
    )

    staged_dir = tmp_path / "0289" / "archives"
    staged_dir.mkdir(parents=True)

    staged = staged_dir / source.filename
    staged.write_bytes(b"corrupt ZIP")

    monkeypatch.setattr(
        cli,
        "archives_dir",
        lambda version: tmp_path / version / "archives",
    )
    monkeypatch.setattr(
        fetch,
        "probe_snaps",
        lambda *args, **kwargs: source,
    )

    download = Mock()
    monkeypatch.setattr(fetch, "snaps_download", download)

    assert cli.cmd_fetch_snaps(make_args()) == 1
    download.assert_not_called()
    assert staged.read_bytes() == b"corrupt ZIP"
