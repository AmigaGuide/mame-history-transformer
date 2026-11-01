from zipfile import ZipFile

from mht.provenance.acquisition import verify_archive_integrity


def test_valid_archive_passes(tmp_path):
    path = tmp_path / "valid.zip"

    with ZipFile(path, "w") as archive:
        archive.writestr("first.txt", "hello")
        archive.writestr("second.txt", "world")

    result = verify_archive_integrity(path)

    assert result["status"] == "passed"
    assert result["members_checked"] == 2
    assert result["bad_member"] is None
    assert result["error"] is None


def test_invalid_zip_reports_error(tmp_path):
    path = tmp_path / "invalid.zip"
    path.write_bytes(b"this is not a ZIP")

    result = verify_archive_integrity(path)

    assert result["status"] == "error"
    assert result["error"] is not None


def test_missing_archive_reports_error(tmp_path):
    path = tmp_path / "missing.zip"

    result = verify_archive_integrity(path)

    assert result["status"] == "error"
    assert result["error"] is not None
