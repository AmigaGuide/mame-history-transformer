from mht.provenance.archives import (
    _stage_provenance_archive,
)


def test_stages_archive_without_renaming(tmp_path):
    incoming = tmp_path / "incoming"
    archives = tmp_path / "archives"

    incoming.mkdir()
    archives.mkdir()

    source = incoming / "history289.zip"
    destination = archives / source.name

    source.write_bytes(b"example archive")

    result = _stage_provenance_archive(
        source,
        destination,
    )

    assert result["action"] == "moved"
    assert destination.read_bytes() == b"example archive"
    assert not source.exists()


def test_existing_destination_is_preserved(tmp_path):
    incoming = tmp_path / "incoming"
    archives = tmp_path / "archives"

    incoming.mkdir()
    archives.mkdir()

    source = incoming / "history289.zip"
    destination = archives / source.name

    source.write_bytes(b"incoming contents")
    destination.write_bytes(b"existing contents")

    result = _stage_provenance_archive(
        source,
        destination,
    )

    assert result["action"] == "skipped"
    assert result["reason"] == "archive_already_staged"

    assert source.read_bytes() == b"incoming contents"
    assert destination.read_bytes() == b"existing contents"

    assert not (
        archives / "history289__dup1.zip"
    ).exists()


def test_filename_mismatch_is_rejected(tmp_path):
    source = tmp_path / "history289.zip"
    destination = tmp_path / "history288.zip"

    source.write_bytes(b"example archive")

    result = _stage_provenance_archive(
        source,
        destination,
    )

    assert result["action"] == "rejected"
    assert result["reason"] == "archive_filename_mismatch"

    assert source.exists()
    assert not destination.exists()


def test_missing_source_is_reported(tmp_path):
    source = tmp_path / "history289.zip"
    destination = tmp_path / "archives" / source.name

    result = _stage_provenance_archive(
        source,
        destination,
    )

    assert result["action"] == "error"
    assert result["reason"] == "source_archive_missing"
    assert not destination.exists()
