import pytest

from tests.util_json_subset import is_subset


def test_exact_match():
    a = {"a": 1, "b": 2}
    b = {"a": 1, "b": 2}
    assert is_subset(a, b)

def test_simple_subset():
    expected = {"a": 1}
    actual = {"a": 1, "b": 2, "c": 3}
    assert is_subset(expected, actual)

def test_nested_subset():
    expected = {"meta": {"version": "1.0"}}
    actual = {"meta": {"version": "1.0", "stamp": "abc123"}, "data": []}
    assert is_subset(expected, actual)

def test_missing_key_fails():
    expected = {"needed": True}
    actual = {"other": 123}
    assert not is_subset(expected, actual)

def test_list_of_scalars_full_match():
    expected = {"tags": ["a", "b"]}
    actual = {"tags": ["a", "b", "c"]}
    # This assumes is_subset requires *all* items from expected list to be present in actual list.
    assert is_subset(expected, actual)

def test_list_of_dicts_subset():
    expected = {
        "items": [
            {"id": 1, "name": "one"},
            {"id": 2},
        ]
    }
    actual = {
        "items": [
            {"id": 2, "name": "two", "extra": True},
            {"id": 1, "name": "one", "more": "ok"},
            {"id": 3},
        ]
    }
    # Assumes list-of-dicts logic: each expected element must match *some* element in the actual list
    # (order-insensitive), with expected as a subset of that element.
    assert is_subset(expected, actual)

def test_type_mismatch_fails():
    expected = {"count": 5}
    actual = {"count": "5"}
    assert not is_subset(expected, actual)

def test_subset_empty_structures():
    # Empty is subset of empty
    assert is_subset({}, {})
    assert is_subset([], [])
    # Empty list is a subset of any list
    assert is_subset([], [1, 2, 3])
    # Empty dict is a subset of any dict
    assert is_subset({}, {"a": 1})
    # But non-empty is not a subset of empty
    assert not is_subset([1], [])
    assert not is_subset({"a": 1}, {})


def test_list_multiset_matching_duplicates_of_dicts():
    sup = [{"a": 1}, {"a": 1}, {"a": 2}]
    # Requires two matches for {"a":1}
    assert is_subset([{"a": 1}, {"a": 1}], sup)
    # Three copies needed but only two available
    assert not is_subset([{"a": 1}, {"a": 1}, {"a": 1}], sup)


def test_list_multiset_matching_duplicates_of_scalars():
    sup = [1, 1, 2, 3]
    assert is_subset([1, 1], sup)
    assert not is_subset([1, 1, 1], sup)
    # Order independence
    assert is_subset([3, 2, 1], sup)


def test_nested_dicts_and_lists_mixed():
    subset = {
        "name": "game-x",
        "meta": {
            "years": [1990, 1991],
            "tags": [{"k": "genre", "v": "shmup"}],
        },
    }
    superset = {
        "name": "game-x",
        "meta": {
            "years": [1989, 1990, 1991, 1992],
            "tags": [
                {"k": "platform", "v": "arcade"},
                {"k": "genre", "v": "shmup"},
            ],
            "extras": True,
        },
        "irrelevant": 123,
    }
    assert is_subset(subset, superset)


def test_none_vs_missing_key_strictness():
    # Missing key should fail subset when expected key exists in subset
    assert not is_subset({"a": None}, {})
    # Present with None must match exactly
    assert is_subset({"a": None}, {"a": None})
    assert not is_subset({"a": None}, {"a": 0})


def test_dict_extra_keys_are_allowed_in_superset():
    subset = {"a": 1}
    superset = {"a": 1, "b": 2, "c": 3}
    assert is_subset(subset, superset)


@pytest.mark.parametrize(
    "subset, superset, expected",
    [
        # Simple scalar lists (multiset logic)
        ([1, 2], [2, 1, 3], True),
        ([1, 2, 2], [2, 1, 2], True),
        ([1, 2, 2], [2, 1], False),

        # Lists of dicts with differing order
        ([{"x": 1}, {"y": 2}], [{"y": 2}, {"x": 1}, {"z": 9}], True),

        # Nested: list-of-dicts inside dict
        (
            {"ports": [{"sys": "amiga", "year": 1991}]},
            {"ports": [{"sys": "snes", "year": 1993}, {"sys": "amiga", "year": 1991}]},
            True,
        ),

        # Type sensitivity: string "1" ≠ int 1
        ({"a": "1"}, {"a": 1}, False),

        # Sub-dict must be satisfied, not just key presence
        ({"obj": {"k": "v"}}, {"obj": {"k": "v", "x": 1}}, True),
        ({"obj": {"k": "v", "m": 1}}, {"obj": {"k": "v"}}, False),
    ],
)
def test_parametric_edge_cases(subset, superset, expected):
    assert is_subset(subset, superset) is expected
