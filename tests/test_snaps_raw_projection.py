from mht.utils.records import project_for_raw


def test_raw_projection_preserves_snaps_classification():
    classification = {
        "group": "Arcade",
        "category": "TTL * Driving",
        "subcategory": "Race Track",
    }

    record = {
        "wiki_page_name": "Example Game",
        "snaps_classification": classification,
        "category": ["Driving"],
        "type": "Arcade Video game",
    }

    raw = project_for_raw("example", record)

    assert raw["machine"] == "example"
    assert raw["snaps_classification"] == classification
    assert raw["category"] == ["Driving"]
    assert "snaps_classification" in raw


def test_raw_projection_does_not_invent_missing_classification():
    record = {
        "wiki_page_name": "Example Game",
        "category": ["Driving"],
    }

    raw = project_for_raw("example", record)

    assert "snaps_classification" not in raw


def test_raw_projection_does_not_add_genre_phrase():
    record = {
        "wiki_page_name": "Road Blaster",
        "snaps_classification": {
            "group": "Arcade",
            "category": "Driving",
            "subcategory": "Guide and Shoot",
        },
    }

    raw = project_for_raw("rblaster", record)

    assert "phrase" not in raw["snaps_classification"]
    assert "opening_sentence" not in raw
