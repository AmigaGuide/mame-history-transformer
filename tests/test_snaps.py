import pytest

from mht.utils.snaps import parse_catlist


def test_arcade_classification():
    content = """
[FOLDER_SETTINGS]
RootFolderIcon mame

[ROOT_FOLDER]

[Arcade: Shooter / Flying Vertical]
1942
1943
"""

    result = parse_catlist(content)

    assert result["1942"] == {
        "group": "Arcade",
        "category": "Shooter",
        "subcategory": "Flying Vertical",
    }

    assert result["1943"] == result["1942"]


def test_non_arcade_classification():
    content = """
[Computer / Home System]
amiga500
"""

    result = parse_catlist(content)

    assert result["amiga500"] == {
        "group": "Non-Arcade",
        "category": "Computer",
        "subcategory": "Home System",
    }


def test_maturity_annotation_does_not_change_genre():
    content = """
[Arcade: Puzzle / Drop * Mature *]
bigtwin
"""

    result = parse_catlist(content)

    assert result["bigtwin"] == {
        "group": "Arcade",
        "category": "Puzzle",
        "subcategory": "Drop",
    }


def test_nested_subcategory_is_preserved():
    content = """
[Handheld / Plug n' Play TV Game / Music]
example
"""

    result = parse_catlist(content)

    assert result["example"]["subcategory"] == (
        "Plug n' Play TV Game / Music"
    )


def test_conflicting_classification_is_rejected():
    content = """
[Arcade: Shooter / Flying Vertical]
example

[Arcade: Puzzle / Drop]
example
"""

    with pytest.raises(ValueError, match="Conflicting"):
        parse_catlist(content)


from mht.utils.snaps import (
    build_snaps_eligible_parents,
    snaps_eligibility_reason,
)


def test_new_arcade_hardware_type_is_accepted():
    mame = {"futuregame": {"cloneof": None}}
    gh = {
        "futuregame": {
            "game_status": "game",
            "type": "Future Arcade System cartridge",
        }
    }
    snaps = {
        "futuregame": {
            "group": "Arcade",
            "category": "Shooter",
            "subcategory": "Flying Vertical",
        }
    }

    assert build_snaps_eligible_parents(
        mame, gh, snaps
    ) == {"futuregame"}


@pytest.mark.parametrize(
    "category",
    [
        "Gambling",
        "Slot Machine",
        "Casino",
        "Medal Game",
        "Electromechanical",
        "Redemption Game",
    ],
)
def test_excluded_arcade_equipment(category):
    mame = {"machine": {"cloneof": None}}
    gh = {
        "machine": {
            "game_status": "game",
            "type": "unknown",
        }
    }
    snaps = {
        "machine": {
            "group": "Arcade",
            "category": category,
            "subcategory": "",
        }
    }

    assert snaps_eligibility_reason(
        "machine", mame, gh, snaps
    ) == "excluded_snaps_category"


def test_explicit_non_game_is_rejected():
    mame = {"diagnostic": {"cloneof": None}}
    gh = {
        "diagnostic": {
            "game_status": "no_game",
            "type": "Arcade Video game",
        }
    }
    snaps = {
        "diagnostic": {
            "group": "Arcade",
            "category": "Shooter",
        }
    }

    assert snaps_eligibility_reason(
        "diagnostic", mame, gh, snaps
    ) == "non_game"


def test_missing_game_status_is_not_assumed_game():
    mame = {"unknown": {"cloneof": None}}
    snaps = {
        "unknown": {
            "group": "Arcade",
            "category": "Platform",
        }
    }

    assert snaps_eligibility_reason(
        "unknown", mame, {}, snaps
    ) == "unknown_game_status"


def test_bios_is_not_ordinary_arcade_game():
    mame = {
        "bios": {
            "cloneof": None,
            "isbios": "yes",
        }
    }
    gh = {
        "bios": {
            "game_status": "game",
            "type": "Arcade Video game",
        }
    }
    snaps = {
        "bios": {
            "group": "Arcade",
            "category": "Shooter",
        }
    }

    assert snaps_eligibility_reason(
        "bios", mame, gh, snaps
    ) == "bios"


def test_clone_is_not_canonical_parent():
    mame = {"clone": {"cloneof": "parent"}}
    gh = {"clone": {"game_status": "game"}}
    snaps = {
        "clone": {
            "group": "Arcade",
            "category": "Shooter",
        }
    }

    assert snaps_eligibility_reason(
        "clone", mame, gh, snaps
    ) == "clone"


def test_mechanical_shooter_is_not_ordinary_eligible():
    mame = {
        "machine": {
            "cloneof": None,
            "ismechanical": "yes",
        }
    }
    gh = {
        "machine": {
            "game_status": "game",
            "type": "Arcade Video game",
        }
    }
    snaps = {
        "machine": {
            "group": "Arcade",
            "category": "Shooter",
        }
    }

    assert snaps_eligibility_reason(
        "machine", mame, gh, snaps
    ) == "mechanical"
