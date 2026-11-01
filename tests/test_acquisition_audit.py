from zipfile import ZipFile

from mht.provenance.acquisition import audit_release_archives


def make_mame_archive(path, version):
    with ZipFile(path, "w") as archive:
        archive.writestr(
            f"mame{version}.xml",
            f'<mame build="0.{version} (mame0{version})" '
            f'mameconfig="10"/>',
        )


def test_matching_archive_is_verified(tmp_path):
    directory = tmp_path / "archives"
    directory.mkdir()

    make_mame_archive(
        directory / "mame0289lx.zip",
        "289",
    )

    records = audit_release_archives(
        "0289",
        archive_directory=directory,
    )

    assert len(records) == 1
    assert records[0]["verification_status"] == "verified"
    assert records[0]["release_verification"] == "match"
    assert (
        records[0]["integrity_verification"]["status"]
        == "passed"
    )


def test_embedded_release_mismatch(tmp_path):
    directory = tmp_path / "archives"
    directory.mkdir()

    make_mame_archive(
        directory / "mame0289lx.zip",
        "288",
    )

    records = audit_release_archives(
        "0289",
        archive_directory=directory,
    )

    assert records[0]["verification_status"] == "mismatch"
    assert records[0]["release_verification"] == "mismatch"


def test_integrity_not_checked_is_not_verified(tmp_path):
    directory = tmp_path / "archives"
    directory.mkdir()

    make_mame_archive(
        directory / "mame0289lx.zip",
        "289",
    )

    records = audit_release_archives(
        "0289",
        archive_directory=directory,
        check_integrity=False,
    )

    assert records[0]["release_verification"] == "match"
    assert (
        records[0]["integrity_verification"]["status"]
        == "not_checked"
    )
    assert records[0]["verification_status"] == "unverified"


def test_corrupt_archive_reports_error(tmp_path):
    directory = tmp_path / "archives"
    directory.mkdir()

    (directory / "mame0289lx.zip").write_bytes(
        b"corrupt archive"
    )

    records = audit_release_archives(
        "0289",
        archive_directory=directory,
    )

    assert records[0]["verification_status"] == "error"
    assert (
        records[0]["integrity_verification"]["status"]
        == "error"
    )
