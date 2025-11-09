"""
Filename: util_json_subset.py
Author: Jason (XtC) Skelly
Project: MAME-History-Transformer (MHT)
Description:
    Utilities to check whether JSON-like structures are a subset of others.
    This is used for small “golden” expectations against larger, evolving outputs
    without forcing exact equality.

Contract (high level):
    - Primitives (str, int, float, bool, None): compare with ==.
    - Dicts: every expected key must exist in actual, and each corresponding value
      must be a subset of the actual value recursively.
    - Lists:
        * list of primitives -> every expected item must appear in actual (order-insensitive).
        * list of dicts      -> every expected dict must match *some* element
                                in actual (order-insensitive), using dict subset logic.
        * mixed lists        -> best-effort: each expected item must match some element
                                of actual using recursive subset semantics.
    - Types must be compatible. We don’t coerce strings ↔ numbers, etc.

Notes:
    - This is intentionally conservative: if in doubt, fail rather than guess.
    - Designed to be fast for unit tests with small fixtures. Not intended for
      full dataset diffs (use your existing validation steps for that).
"""

from __future__ import annotations
from typing import Any


def is_subset(expected: Any, actual: Any) -> bool:
    """
    Public entry point.
    Returns True if `expected` is a subset of `actual` under the rules above.
    """
    return _match(expected, actual)


# ---------------------------- internal helpers ---------------------------- #

def _match(expected: Any, actual: Any) -> bool:
    """Dispatch based on type."""
    # Exact type families first
    if isinstance(expected, dict):
        return isinstance(actual, dict) and _dict_is_subset(expected, actual)

    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return _list_is_subset(expected, actual)

    # Primitives: accept int==float if numerically equal (tiny convenience)
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return float(expected) == float(actual)

    # Fallback to simple equality for str/bool/None/others
    return expected == actual


def _dict_is_subset(exp: dict, act: dict) -> bool:
    """
    Every key in `exp` must exist in `act` and each value must match recursively.
    """
    for k, exp_v in exp.items():
        if k not in act:
            return False
        if not _match(exp_v, act[k]):
            return False
    return True


def _list_is_subset(exp_list: list, act_list: list) -> bool:
    """
    List rules:
      - primitives: each expected item must be present in actual (>= multiplicity).
      - dicts: each expected dict must match some element of actual (order-insensitive).
      - mixed: try to match each expected element to some actual element.
    """
    if not exp_list:
        return True  # empty is subset of anything

    # Fast-path checks for homogeneous lists
    if _is_all_primitives(exp_list):
        return _prims_list_is_subset(exp_list, act_list)

    if _is_all_dicts(exp_list):
        return _list_of_dicts_is_subset(exp_list, act_list)

    # Mixed list: greedy match
    used = [False] * len(act_list)
    for exp_item in exp_list:
        matched = False
        for i, act_item in enumerate(act_list):
            if used[i]:
                continue
            if _match(exp_item, act_item):
                used[i] = True
                matched = True
                break
        if not matched:
            return False
    return True


def _prims_list_is_subset(exp_list: list, act_list: list) -> bool:
    """
    Multiset containment for primitives: every expected value must appear in the actual
    list at least as many times. Comparisons are == (with numeric int/float tolerance).
    """
    # Build multiset for actual with a normalised key that merges int/float 1 == 1.0
    def key(v: Any):
        if isinstance(v, (int, float)):
            return ("num", float(v))
        return ("val", v)

    from collections import Counter
    act_counts = Counter(key(v) for v in act_list)
    exp_counts = Counter(key(v) for v in exp_list)

    for k, needed in exp_counts.items():
        if act_counts[k] < needed:
            return False
    return True


def _list_of_dicts_is_subset(exp_list: list[dict], act_list: list[Any]) -> bool:
    """
    Each expected dict must be a subset of *some* element in the actual list.
    Actual may contain mixed types; only dicts are eligible to satisfy dict expectations.
    Elements can’t be reused once matched (greedy).
    """
    # Indices of actual dict elements
    act_candidates = [i for i, v in enumerate(act_list) if isinstance(v, dict)]
    used = set()

    for exp_d in exp_list:
        found = False
        for i in act_candidates:
            if i in used:
                continue
            if _dict_is_subset(exp_d, act_list[i]):
                used.add(i)
                found = True
                break
        if not found:
            return False
    return True


def _is_all_primitives(seq: list) -> bool:
    return all(not isinstance(x, (dict, list)) for x in seq)


def _is_all_dicts(seq: list) -> bool:
    return all(isinstance(x, dict) for x in seq)
