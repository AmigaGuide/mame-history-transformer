from mht.utils.selection import (
    build_eligible_parents_set,
    build_final_set,
)
from mht.utils.ports import gh_keys_with_any_valid_ports


def sample_mame():
    return {
        "arcade": {"cloneof": None},
        "arcade_clone": {"cloneof": "arcade"},
        "pinball": {"cloneof": None, "ismechanical": True},
        "handheld": {"cloneof": None},
        "bios": {"cloneof": None, "isbios": True},
    }


def sample_classifications():
    return {
        "arcade": {
            "game_status": "game",
            "category": ["Arcade"],
            "type": "Video Game",
        },
        "arcade_clone": {
            "game_status": "game",
            "category": ["Arcade"],
            "type": "Video Game",
        },
        "pinball": {
            "game_status": "game",
            "category": ["Coin-Op (Games)"],
            "type": "Pinball",
        },
        "handheld": {
            "game_status": "game",
            "category": ["Electronic"],
            "type": "Handheld",
        },
        "bios": {
            "game_status": "no_game",
            "category": ["unknown"],
            "type": "BIOS",
        },
    }


def sample_parent_index():
    return {
        "parents": {
            "arcade": ["arcade_clone"],
        },
        "child_to_parent": {
            "arcade_clone": "arcade",
        },
    }


def sample_ports():
    return {
        "arcade": {
            "ports": {
                "Home": [{"platform": "Amiga"}],
            }
        },
        "pinball": {
            "ports": {
                "Home": [{"platform": "PC"}],
            }
        },
        "handheld": {
            "ports": {
                "Home": [{"platform": "Game & Watch"}],
            }
        },
        "bios": {
            "ports": {
                "Home": [{"platform": ""}],
            }
        },
    }


def test_arcade_eligibility_excludes_clones_and_other_categories():
    eligible = build_eligible_parents_set(
        sample_mame(),
        sample_classifications(),
    )

    assert eligible == {"arcade"}


def test_final_set_adds_clones_from_mame_index():
    result = build_final_set(
        {"arcade"},
        sample_parent_index(),
    )

    assert result == {"arcade", "arcade_clone"}


def test_valid_ports_identifies_exception_candidates():
    valid = gh_keys_with_any_valid_ports(sample_ports())

    assert valid == {"arcade", "pinball", "handheld"}

    eligible = build_eligible_parents_set(
        sample_mame(),
        sample_classifications(),
    )

    exceptions = valid - eligible

    assert exceptions == {"pinball", "handheld"}


def test_invalid_bios_ports_do_not_create_exception():
    valid = gh_keys_with_any_valid_ports(sample_ports())

    assert "bios" not in valid


def test_parent_selection_preserves_clone_only_ports():
    from mht.utils.selection import build_ports_parent_selection

    mame = {
        "parent": {"cloneof": None},
        "clone": {"cloneof": "parent"},
    }

    classifications = {
        "parent": {
            "game_status": "game",
            "category": ["Arcade"],
        },
    }

    index = {
        "parents": {"parent": ["clone"]},
        "child_to_parent": {"clone": "parent"},
    }

    eligible, selected, exceptions = build_ports_parent_selection(
        mame, classifications, index, {"clone"}
    )

    assert eligible == {"parent"}
    assert selected == {"parent"}
    assert exceptions == set()


def test_parent_selection_preserves_exception_with_clone_only_ports():
    from mht.utils.selection import build_ports_parent_selection

    mame = {
        "pinball": {"cloneof": None, "ismechanical": True},
        "pinball_clone": {"cloneof": "pinball"},
    }

    classifications = {
        "pinball": {
            "game_status": "game",
            "category": ["Coin-Op (Games)"],
        },
    }

    index = {
        "parents": {"pinball": ["pinball_clone"]},
        "child_to_parent": {
            "pinball_clone": "pinball",
        },
    }

    eligible, selected, exceptions = build_ports_parent_selection(
        mame, classifications, index, {"pinball_clone"}
    )

    assert eligible == set()
    assert selected == {"pinball"}
    assert exceptions == {"pinball"}


def test_parent_selection_keeps_ports_exceptions_separate():
    from mht.utils.selection import build_ports_parent_selection

    eligible, selected, exceptions = build_ports_parent_selection(
        sample_mame(),
        sample_classifications(),
        sample_parent_index(),
        {"arcade", "pinball", "handheld"},
    )

    assert eligible == {"arcade"}
    assert selected == {"arcade", "pinball", "handheld"}
    assert exceptions == {"pinball", "handheld"}
