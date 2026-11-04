from mht.transform import pipeline


def test_unapproved_genre_aborts_before_writing(monkeypatch, tmp_path):
    """
    A publishable game with an unapproved SNAPS classification
    must abort the transformation before any output is written.
    """

    def unexpected_write(*args, **kwargs):
        raise AssertionError(
            "Transformer attempted to write after genre validation failed"
        )

    # Keep the test isolated from the real release directories.
    monkeypatch.setattr(
        pipeline, "ensure_release_dirs", lambda: None
    )
    monkeypatch.setattr(
        pipeline, "find_snaps_archive", lambda _: tmp_path / "snaps.zip"
    )
    monkeypatch.setattr(
        pipeline, "stage_is_fresh",
        lambda *args, **kwargs: (
            False, tmp_path / "transform.json", {}
        ),
    )
    monkeypatch.setattr(
        pipeline, "_load_title_overrides", lambda _: {}
    )

    # One fictional MAME parent with Gaming History PORTS.
    monkeypatch.setattr(
        pipeline,
        "load_stage_inputs",
        lambda: (
            {"example": {"description": "Example Game"}},
            {"parents": {}, "child_to_parent": {}},
            {"example": {}},
            {},
        ),
    )

    snaps = {
        "example": {
            "group": "Arcade",
            "category": "Unreviewed Category",
            "subcategory": "Unknown Gameplay",
        }
    }

    monkeypatch.setattr(
        pipeline, "load_release_snaps", lambda _: snaps
    )
    monkeypatch.setattr(
        pipeline, "_gh_keys_with_any_valid_ports",
        lambda _: {"example"},
    )
    monkeypatch.setattr(
        pipeline, "build_eligible_parents_set",
        lambda *args: set(),
    )
    monkeypatch.setattr(
        pipeline, "build_ports_parent_set",
        lambda *args: {"example"},
    )
    monkeypatch.setattr(
        pipeline, "extract_stage_versions_for_transform",
        lambda *args: ({}, {}),
    )

    # Supply one assembled parent without requiring real PORTS data.
    telemetry = {
        "parents_with_any_media": False,
        "media_labels_for_counts": set(),
        "ignored_devices": {},
        "audio_channels_reported": 0,
        "speaker_sum": 0,
        "samples_required": False,
        "parent_has_ports": False,
        "clones_with_ports": set(),
        "has_parent_clone_port_dupes": False,
    }

    monkeypatch.setattr(
        pipeline,
        "build_parent_record",
        lambda **kwargs: (
            {"mame_titles": [], "ports": {}},
            telemetry,
        ),
    )
    monkeypatch.setattr(
        pipeline, "_render_mame_titles_display", lambda _: ""
    )
    monkeypatch.setattr(
        pipeline, "_build_redirect_sources",
        lambda *args: [],
    )
    monkeypatch.setattr(
        pipeline, "render_ports_display",
        lambda *args: "",
    )

    # Existing approved wording does not cover the fictional category.
    monkeypatch.setattr(
        pipeline,
        "load_approved_genres",
        lambda: {
            ("Arcade", "Driving", "Race Track"):
                "a racing arcade video game"
        },
    )
    monkeypatch.setattr(
        pipeline,
        "partition_ports_parents",
        lambda *args: ({"example"}, {}),
    )

    # Any attempt to publish or save the transform stamp is a failure.
    monkeypatch.setattr(pipeline, "write_json", unexpected_write)
    monkeypatch.setattr(
        pipeline, "write_pages_and_redirects", unexpected_write
    )
    monkeypatch.setattr(pipeline, "save_stamp", unexpected_write)

    assert pipeline.run_transformer() is False
