from mht.utils.snaps import partition_ports_parents


def test_ports_parents_are_partitioned_without_discarding_them():
    mame = {
        "arcade": {"cloneof": None, "ismechanical": "no"},
        "mechanical": {"cloneof": None, "ismechanical": "yes"},
        "unknown": {"cloneof": None, "ismechanical": "no"},
    }

    gh = {
        "arcade": {"game_status": "game", "type": "Arcade Video game"},
        "mechanical": {"game_status": "game", "type": "Arcade Video game"},
        "unknown": {"game_status": "unknown", "type": "unknown"},
    }

    snaps = {
        "arcade": {"group": "Arcade", "category": "Maze"},
        "mechanical": {
            "group": "Arcade",
            "category": "Electromechanical",
        },
        "unknown": {"group": "Arcade", "category": "Maze"},
    }

    ports_parents = {"arcade", "mechanical", "unknown"}

    publishable, deferred = partition_ports_parents(
        ports_parents,
        mame,
        gh,
        snaps,
    )

    assert publishable == {"arcade"}
    assert deferred == {
        "mechanical": "excluded_snaps_category",
        "unknown": "unknown_game_status",
    }

    assert publishable.isdisjoint(deferred)
    assert publishable | set(deferred) == ports_parents


def test_missing_snaps_does_not_grant_publication():
    mame = {"arcade": {"cloneof": None}}
    gh = {"arcade": {"game_status": "game"}}

    publishable, deferred = partition_ports_parents(
        {"arcade"},
        mame,
        gh,
        {},
    )

    assert publishable == set()
    assert deferred == {"arcade": "missing_snaps_classification"}
