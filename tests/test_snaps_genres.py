import json

import pytest

from mht.transform.snaps_genres import (
    load_approved_genres,
    validate_published_genres,
)


def test_committed_vocabulary_has_134_unique_keys():
    lookup = load_approved_genres()

    assert len(lookup) == 134
    assert all(phrase.startswith(("a ", "an ")) for phrase in lookup.values())


def test_committed_vocabulary_preserves_ttl_keys():
    lookup = load_approved_genres()

    assert (
        "Arcade",
        "TTL * Ball & Paddle",
        "Breakout",
    ) in lookup


def test_duplicate_classification_is_rejected(tmp_path):
    path = tmp_path / "genres.json"

    entry = {
        "group": "Arcade",
        "category": "Driving",
        "subcategory": "Race Track",
        "phrase": "a racing arcade video game",
    }

    path.write_text(
        json.dumps([entry, entry]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate"):
        load_approved_genres(path)


def test_incomplete_vocabulary_entry_is_rejected(tmp_path):
    path = tmp_path / "genres.json"

    path.write_text(
        json.dumps([
            {
                "group": "Arcade",
                "category": "Driving",
                "subcategory": "Race Track",
            }
        ]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="exactly"):
        load_approved_genres(path)


def test_published_games_with_approved_keys_pass():
    lookup = {
        ("Arcade", "Driving", "Race Track"): (
            "a racing arcade video game"
        )
    }

    snaps = {
        "example": {
            "group": "Arcade",
            "category": "Driving",
            "subcategory": "Race Track",
        }
    }

    validate_published_genres({"example"}, snaps, lookup)


def test_unapproved_classification_blocks_publication():
    lookup = {
        ("Arcade", "Driving", "Race Track"): (
            "a racing arcade video game"
        )
    }

    snaps = {
        "example": {
            "group": "Arcade",
            "category": "Driving",
            "subcategory": "Unknown New Category",
        }
    }

    with pytest.raises(ValueError, match="Unknown New Category"):
        validate_published_genres({"example"}, snaps, lookup)


def test_missing_snaps_record_blocks_publication():
    with pytest.raises(ValueError, match="Missing or incomplete"):
        validate_published_genres({"example"}, {}, {})


def test_unpublished_classifications_do_not_block_publication():
    lookup = {
        ("Arcade", "Driving", "Race Track"): (
            "a racing arcade video game"
        )
    }

    snaps = {
        "published": {
            "group": "Arcade",
            "category": "Driving",
            "subcategory": "Race Track",
        },
        "unpublished": {
            "group": "Arcade",
            "category": "Something New",
            "subcategory": "Unreviewed",
        },
    }

    validate_published_genres({"published"}, snaps, lookup)
