from zipfile import ZipFile

from mht.provenance.acquisition import inspect_archive_metadata


def test_mame_embedded_version(tmp_path):
    path = tmp_path / "mame0289lx.zip"

    with ZipFile(path, "w") as archive:
        archive.writestr(
            "mame0289.xml",
            '<mame build="0.289 (mame0289)" mameconfig="10"/>',
        )

    result = inspect_archive_metadata(path, "0289")

    assert result["error"] is None
    assert result["embedded_version"] == "0.289 (mame0289)"
    assert result["comparison"]["status"] == "match"


def test_history_embedded_version(tmp_path):
    path = tmp_path / "history287a.zip"

    with ZipFile(path, "w") as archive:
        archive.writestr(
            "history/history.xml",
            '<history version="2.87a" date="2026-04-11"/>',
        )

    result = inspect_archive_metadata(path, "0287")

    assert result["error"] is None
    assert result["embedded_version"] == "2.87a"
    assert result["embedded_date"] == "2026-04-11"
    assert result["comparison"]["status"] == "match"


def test_history_mismatch_is_detected(tmp_path):
    path = tmp_path / "history288.zip"

    with ZipFile(path, "w") as archive:
        archive.writestr(
            "history/history.xml",
            '<history version="2.89" date="2026-08-07"/>',
        )

    result = inspect_archive_metadata(path, "0288")

    assert result["comparison"]["status"] == "mismatch"


def test_snaps_embedded_metadata(tmp_path):
    path = tmp_path / "pS_CatVer_289.zip"

    with ZipFile(path, "w") as archive:
        archive.writestr(
            "UI_files/catlist.ini",
            ";; CATLIST.ini 0.289 / 21-Aug-26 / MAME 0.289 ;;\n"
            "[Arcade: Maze / Collect]\npuckman\n",
        )

    result = inspect_archive_metadata(path, "0289")

    assert result["error"] is None
    assert result["embedded_version"] == "0.289"
    assert result["embedded_date"] == "21-Aug-26"
    assert result["comparison"]["status"] == "match"


def test_invalid_zip_reports_error(tmp_path):
    path = tmp_path / "mame0289lx.zip"
    path.write_bytes(b"not a ZIP archive")

    result = inspect_archive_metadata(path, "0289")

    assert result["error"] is not None
