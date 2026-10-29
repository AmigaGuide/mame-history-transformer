from mht.utils.classification_catalog import (
    build_classification_catalog,
)


def test_both_sources_are_preserved():
    catalog = build_classification_catalog(
        {
            "sbm": {
                "cloneof": None,
                "isbios": "no",
                "isdevice": "no",
                "ismechanical": "yes",
            }
        },
        {
            "sbm": {
                "game_status": "game",
                "category": ["Arcade"],
                "type": "Arcade Video game",
            }
        },
        {
            "sbm": {
                "group": "Arcade",
                "category": "Electromechanical",
                "subcategory": "Misc.",
            }
        },
    )

    row = catalog["sbm"]

    assert row["mame"]["ismechanical"] == "yes"
    assert row["gaming_history"]["category"] == ["Arcade"]
    assert row["snaps"]["category"] == "Electromechanical"


def test_missing_gh_source_is_not_inferred():
    catalog = build_classification_catalog(
        {"example": {"cloneof": None}},
        {},
        {
            "example": {
                "group": "Arcade",
                "category": "Shooter",
                "subcategory": "Flying Vertical",
            }
        },
    )

    assert catalog["example"]["gaming_history"] is None
    assert catalog["example"]["snaps"]["group"] == "Arcade"


def test_missing_snaps_source_is_not_inferred():
    catalog = build_classification_catalog(
        {"example": {"cloneof": None}},
        {
            "example": {
                "game_status": "game",
                "category": ["Arcade"],
                "type": "Arcade Video game",
            }
        },
        {},
    )

    assert catalog["example"]["snaps"] is None
    assert catalog["example"]["gaming_history"][
        "category"
    ] == ["Arcade"]


def test_clone_does_not_automatically_inherit_gh():
    catalog = build_classification_catalog(
        {
            "parent": {"cloneof": None},
            "clone": {"cloneof": "parent"},
        },
        {
            "parent": {
                "game_status": "game",
                "category": ["Arcade"],
            }
        },
        {},
    )

    assert catalog["parent"]["gaming_history"] is not None
    assert catalog["clone"]["gaming_history"] is None
    assert catalog["clone"]["mame"]["cloneof"] == "parent"


def test_source_data_is_not_modified():
    gh = {
        "example": {
            "game_status": "game",
            "category": ["Arcade"],
        }
    }

    catalog = build_classification_catalog(
        {"example": {}}, gh, {}
    )

    catalog["example"]["gaming_history"][
        "category"
    ].append("Something Else")

    assert gh["example"]["category"] == ["Arcade"]


def test_historical_category_is_preserved_separately():
    catalog = build_classification_catalog(
        {"1942": {"cloneof": None}},
        {
            "1942": {
                "game_status": "game",
                "category": ["unknown"],
                "type": "Arcade Video game",
            }
        },
        {
            "1942": {
                "group": "Arcade",
                "category": "Shooter",
                "subcategory": "Flying Vertical",
            }
        },
        {
            "1942": {
                "category": ["Arcade"],
                "source_release": "0287",
                "requested_release": "0288",
                "status": "carried_forward",
            }
        },
    )

    row = catalog["1942"]

    assert row["gaming_history"]["category"] == ["unknown"]
    assert row["gaming_history_historical"]["category"] == ["Arcade"]
    assert row["gaming_history_historical"]["source_release"] == "0287"
    assert row["gaming_history_historical"]["status"] == "carried_forward"
    assert row["snaps"]["category"] == "Shooter"


def test_historical_source_remains_optional():
    catalog = build_classification_catalog(
        {"example": {}},
        {},
        {},
    )

    assert catalog["example"]["gaming_history_historical"] is None


def test_historical_categories_are_not_mutated():
    historical = {
        "example": {
            "category": ["Arcade"],
            "source_release": "0287",
            "requested_release": "0289",
            "status": "carried_forward",
        }
    }

    catalog = build_classification_catalog(
        {"example": {}},
        {},
        {},
        historical,
    )

    catalog["example"]["gaming_history_historical"][
        "category"
    ].append("Gambling")

    assert historical["example"]["category"] == ["Arcade"]
