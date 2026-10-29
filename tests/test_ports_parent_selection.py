from mht.utils.selection import build_ports_parent_set


def test_parent_with_ports():
    mame = {
        "arcade": {"cloneof": None},
    }

    result = build_ports_parent_set(
        mame,
        {},
        {"arcade"},
    )

    assert result == {"arcade"}


def test_clone_only_ports_resolve_to_parent():
    mame = {
        "parent": {"cloneof": None},
        "clone": {"cloneof": "parent"},
    }

    index = {
        "child_to_parent": {"clone": "parent"},
    }

    result = build_ports_parent_set(
        mame,
        index,
        {"clone"},
    )

    assert result == {"parent"}


def test_parent_and_clone_do_not_duplicate():
    mame = {
        "parent": {"cloneof": None},
        "clone": {"cloneof": "parent"},
    }

    result = build_ports_parent_set(
        mame,
        {},
        {"parent", "clone"},
    )

    assert result == {"parent"}


def test_non_arcade_machine_is_preserved():
    mame = {
        "handheld": {"cloneof": None},
        "pinball": {
            "cloneof": None,
            "ismechanical": "yes",
        },
    }

    result = build_ports_parent_set(
        mame,
        {},
        {"handheld", "pinball"},
    )

    assert result == {"handheld", "pinball"}


def test_unrecognised_gh_machine_is_ignored():
    result = build_ports_parent_set(
        {"arcade": {"cloneof": None}},
        {},
        {"not_in_mame"},
    )

    assert result == set()


def test_clone_with_missing_parent_is_ignored():
    mame = {
        "orphan": {"cloneof": "missing_parent"},
    }

    result = build_ports_parent_set(
        mame,
        {},
        {"orphan"},
    )

    assert result == set()


def test_invalid_parent_chain_is_ignored():
    mame = {
        "clone": {"cloneof": "intermediate"},
        "intermediate": {"cloneof": "real_parent"},
        "real_parent": {"cloneof": None},
    }

    result = build_ports_parent_set(
        mame,
        {},
        {"clone"},
    )

    # Preserve existing one-level resolution behaviour.
    assert result == set()
