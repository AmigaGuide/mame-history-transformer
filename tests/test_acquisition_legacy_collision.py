from mht.provenance import archives


def test_legacy_collision_reports_actual_destination(
    monkeypatch,
    tmp_path,
):
    incoming = tmp_path / "incoming"
    incoming.mkdir()

    releases = tmp_path / "releases"

    source = incoming / "history289.zip"
    source.write_bytes(b"new archive contents")

    archive_dir = releases / "0289" / "archives"
    archive_dir.mkdir(parents=True)

    existing = archive_dir / "history289.zip"
    existing.write_bytes(b"existing archive contents")

    monkeypatch.setattr(
        archives,
        "archives_dir",
        lambda release: releases / release / "archives",
    )

    monkeypatch.setattr(
        archives,
        "ensure_release_dirs",
        lambda release: (
            releases / release / "archives"
        ).mkdir(parents=True, exist_ok=True),
    )

    results = archives.import_incoming_archives(
        incoming=incoming,
    )

    assert len(results) == 1

    result = results[0]
    duplicate = archive_dir / "history289__dup1.zip"

    assert result["action"] == "moved"
    assert result["version"] == "0289"
    assert result["dest_archive"] == duplicate.as_posix()

    assert existing.read_bytes() == b"existing archive contents"
    assert duplicate.read_bytes() == b"new archive contents"
    assert not source.exists()
