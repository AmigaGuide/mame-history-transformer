from mht.transform import pipeline


def test_missing_snaps_archive_aborts_before_transform(
    monkeypatch,
    tmp_path,
):
    # Use an isolated directory, not the real release archives.
    archive_dir = tmp_path / "archives"
    archive_dir.mkdir()

    monkeypatch.setattr(
        pipeline,
        "archives_dir",
        lambda: archive_dir,
    )

    monkeypatch.setattr(
        pipeline,
        "ensure_release_dirs",
        lambda: None,
    )

    # A missing SNAPS archive must abort before checking stamps
    # or attempting to load any transformation inputs.
    def unexpected_call(*args, **kwargs):
        raise AssertionError(
            "Transformer continued after missing SNAPS archive"
        )

    monkeypatch.setattr(
        pipeline,
        "stage_is_fresh",
        unexpected_call,
    )
    monkeypatch.setattr(
        pipeline,
        "load_stage_inputs",
        unexpected_call,
    )

    assert pipeline.run_transformer() is False


def test_multiple_snaps_archives_abort_before_transform(
    monkeypatch,
    tmp_path,
):
    archive_dir = tmp_path / "archives"
    archive_dir.mkdir()

    (archive_dir / "pS_SupportFiles_287.zip").touch()
    (archive_dir / "pS_CatVer_287.zip").touch()

    monkeypatch.setattr(
        pipeline,
        "archives_dir",
        lambda: archive_dir,
    )
    monkeypatch.setattr(
        pipeline,
        "ensure_release_dirs",
        lambda: None,
    )

    def unexpected_call(*args, **kwargs):
        raise AssertionError(
            "Transformer continued with ambiguous SNAPS archives"
        )

    monkeypatch.setattr(
        pipeline,
        "stage_is_fresh",
        unexpected_call,
    )
    monkeypatch.setattr(
        pipeline,
        "load_stage_inputs",
        unexpected_call,
    )

    assert pipeline.run_transformer() is False
