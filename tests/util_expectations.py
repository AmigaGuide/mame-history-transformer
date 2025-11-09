"""
Lightweight matchers for trivia 'golden' fixtures.

Supported expectation keys per block:
- Common:
    type:               exact match on block["type"]
    text_contains:      substring required in block["text"]
    text_not_contains:  substring forbidden in block["text"]

- Lists (bullet_list / numbered_list):
    any_item_contains:      [substring, ...]  -> at least one list item contains any of these
    any_item_not_contains:  [substring, ...]  -> no list item may contain any of these

- Pairs (type == "pair"):
    label_contains:         substring required in block["label"]
    label_not_contains:     substring forbidden in block["label"]
    value_contains:         substring required in block["value"]
    value_not_contains:     substring forbidden in block["value"]

Section-wide directive (placed as a 'block' in expectations list):
    {"forbid_section_text": ["snippet A", "snippet B", ...]}

Usage:
    blocks_satisfy_expectations(expected_blocks, actual_blocks) -> bool
"""

from __future__ import annotations

from typing import Any, Dict, List

__all__ = [
    "match_block_expectation",
    "blocks_satisfy_expectations",
]

# ---------------------------------------------------------------------------

def _block_text_fields(actual: Dict[str, Any]) -> List[str]:
    """
    Collect all human-readable text fields from a block for negative/forbid checks.
    Safely handles absent/None fields.
    """
    out: List[str] = []
    t = actual.get("text")
    if isinstance(t, str):
        out.append(t)
    lbl = actual.get("label")
    if isinstance(lbl, str):
        out.append(lbl)
    val = actual.get("value")
    if isinstance(val, str):
        out.append(val)
    items = actual.get("items")
    if isinstance(items, list):
        out.extend([str(x) for x in items if isinstance(x, (str, int, float))])
    return out


def _section_forbids_pass(forbids: List[str], actual_blocks: List[Dict[str, Any]]) -> bool:
    """
    Ensure none of the forbidden snippets appear in ANY text/label/value/items across the section.
    """
    if not forbids:
        return True
    hay = " \n ".join(s for b in actual_blocks for s in _block_text_fields(b))
    return all(snippet not in hay for snippet in forbids)

# ---------------------------------------------------------------------------

def match_block_expectation(expected: Dict[str, Any], actual: Dict[str, Any]) -> bool:
    """
    Does a single actual block satisfy a single expected block spec?
    Returns True on match, False otherwise.
    """
    # Type guard (if specified)
    if "type" in expected:
        if expected["type"] != actual.get("type"):
            return False

    # Text fields (paragraph/subheading)
    txt = actual.get("text") or ""
    if "text_contains" in expected and expected["text_contains"] not in txt:
        return False
    if "text_not_contains" in expected and expected["text_not_contains"] in txt:
        return False

    # Lists
    items = actual.get("items") or []
    if "any_item_contains" in expected:
        needles = [n for n in expected["any_item_contains"] if isinstance(n, str) and n]
        if needles:
            found_any = any(any(n in (it or "") for n in needles) for it in items)
            if not found_any:
                return False
    if "any_item_not_contains" in expected:
        bans = [b for b in expected["any_item_not_contains"] if isinstance(b, str) and b]
        if bans:
            found_forbidden = any(any(b in (it or "") for b in bans) for it in items)
            if found_forbidden:
                return False

    # Pairs
    if actual.get("type") == "pair":
        label = actual.get("label") or ""
        value = actual.get("value") or ""
        if "label_contains" in expected and expected["label_contains"] not in label:
            return False
        if "label_not_contains" in expected and expected["label_not_contains"] in label:
            return False
        if "value_contains" in expected and expected["value_contains"] not in value:
            return False
        if "value_not_contains" in expected and expected["value_not_contains"] in value:
            return False

    return True

# ---------------------------------------------------------------------------

def blocks_satisfy_expectations(expected_blocks: List[Dict[str, Any]],
                                actual_blocks: List[Dict[str, Any]]) -> bool:
    """
    Section-level matcher:
      - Every positive expected block spec must match at least one of the actual blocks.
      - Any forbid directive {'forbid_section_text': [...]} must hold across the whole section.
    """
    if not isinstance(expected_blocks, list):
        return False

    # Separate section-wide forbids from positive expectations
    section_forbids: List[str] = []
    positive: List[Dict[str, Any]] = []

    for eb in expected_blocks:
        if isinstance(eb, dict) and "forbid_section_text" in eb:
            vals = eb.get("forbid_section_text") or []
            section_forbids.extend([v for v in vals if isinstance(v, str) and v.strip()])
        else:
            positive.append(eb)

    # Positive expectations
    for exp in positive:
        matched = any(match_block_expectation(exp, act) for act in actual_blocks)
        if not matched:
            return False

    # Section-wide forbids
    if not _section_forbids_pass(section_forbids, actual_blocks):
        return False

    return True
