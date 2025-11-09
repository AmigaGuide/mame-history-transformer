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

from typing import Any, Dict, List, Tuple
import re


def _normalise_text(s: Any) -> str:
    return ("" if s is None else str(s)).strip()

def _contains_ci(hay: Any, needle: Any) -> bool:
    h = _normalise_text(hay).lower()
    n = _normalise_text(needle).lower()
    if not n:
        return True
    return n in h

def _text_in_block(exp_text: str, act_block: Dict[str, Any]) -> bool:
    """Case-insensitive containment across common text carriers."""
    if _contains_ci(act_block.get("text"), exp_text):
        return True
    # Check list items (for list-like blocks)
    items = act_block.get("items") or []
    for it in items:
        if _contains_ci(it, exp_text):
            return True
    return False

def _collect_numbered_list_items(act_blocks: List[Dict[str, Any]]) -> List[str]:
    """Gather all item strings from all numbered_list actual blocks."""
    acc: List[str] = []
    for b in act_blocks:
        if b.get("type") == "numbered_list":
            items = b.get("items") or []
            acc.extend(_normalise_text(x) for x in items)
    return acc

def _text_carrier(block: Dict[str, Any]) -> str:
    """Concatenate user-visible text for any block."""
    t = []
    bt = block.get("type")
    if bt == "pair":
        t.append(str(block.get("key") or ""))
        t.append(str(block.get("value") or ""))
    else:
        if block.get("text"):
            t.append(str(block["text"]))
        for it in (block.get("items") or []):
            t.append(str(it))
    return " ".join(t)

def _norm(s: str) -> str:
    return (s or "").lower()

def _contains(hay: str, needle: str) -> bool:
    return _norm(needle) in _norm(hay)

def _any_contains(hay: str, needles: List[str]) -> bool:
    return any(_contains(hay, n) for n in needles if n)

def _all_contains(hay: str, needles: List[str]) -> bool:
    return all(_contains(hay, n) for n in needles if n)

def _match_text_expectation(exp: Dict[str, Any], carrier: str) -> bool:
    """
    Flexible text matching:
      - text_contains: str OR [str,...] (ALL must match if list)
      - any_text_contains: [str,...] (ANY may match)
      - text_regex: str (re.search)
    """
    if "text_contains" in exp:
        tc = exp["text_contains"]
        if isinstance(tc, list):
            if not _all_contains(carrier, tc):
                return False
        else:
            if not _contains(carrier, str(tc)):
                return False

    if "any_text_contains" in exp:
        if not _any_contains(carrier, list(exp["any_text_contains"] or [])):
            return False

    if "text_regex" in exp:
        try:
            if not re.search(exp["text_regex"], carrier, flags=re.IGNORECASE | re.MULTILINE):
                return False
        except re.error:
            # Invalid regex -> hard fail for safety
            return False

    return True

def _match_pair_expectation(exp: Dict[str, Any], block: Dict[str, Any], carrier: str) -> bool:
    """
    'pair' expectations succeed if:
      - actual is a pair and key/value constraints hold; OR
      - fallback: the carrier text mentions the key/value anchors.
    """
    key_need = exp.get("key_contains")
    val_need = exp.get("value_contains")

    if block.get("type") == "pair":
        if key_need and not _contains(str(block.get("key", "")), key_need):
            return False
        if val_need and not _contains(str(block.get("value", "")), val_need):
            return False
        return _match_text_expectation(exp, carrier)

    # fallback to carrier search (paragraph/list merged content)
    if key_need and not _contains(carrier, key_need):
        return False
    if val_need and not _contains(carrier, val_need):
        return False
    return _match_text_expectation(exp, carrier)

def _block_matches(exp_block: Dict[str, Any], act_block: Dict[str, Any]) -> bool:
    """
    Content-first matcher with soft 'type'.
    Supports keys:
      - type: "paragraph" | "numbered_list" | "bulleted_list" | "pair" (soft)
      - text_contains: str OR [str,...]
      - any_text_contains: [str,...]
      - text_regex: str
      - key_contains / value_contains: for 'pair' semantics
    """
    carrier = _text_carrier(act_block)
    exp_type = exp_block.get("type")

    # If 'pair' semantics are requested in any way, handle specially
    if exp_type == "pair" or "key_contains" in exp_block or "value_contains" in exp_block:
        return _match_pair_expectation(exp_block, act_block, carrier)

    # Otherwise generic text-based check
    return _match_text_expectation(exp_block, carrier)

def blocks_satisfy_expectations(exp_blocks: List[Dict[str, Any]], act_blocks: List[Dict[str, Any]]) -> bool:
    """
    Each expected block must be satisfied by at least one actual block.
    Actual blocks are NOT consumed, allowing multiple expectations to match the same block.
    """
    for eb in exp_blocks or []:
        if not any(_block_matches(eb, ab) for ab in (act_blocks or [])):
            return False
    return True

# --- Diagnostics to speed up fixture tuning ---

def explain_expectation_mismatches(exp_blocks: List[Dict[str, Any]], act_blocks: List[Dict[str, Any]], top_k: int = 3) -> List[str]:
    """
    Returns human-readable hints for unmet expectations:
      - shows the expectation
      - shows top_k candidate actual blocks ranked by token overlap
    """
    def score(exp: Dict[str, Any], carrier: str) -> int:
        toks: List[str] = []
        tc = exp.get("text_contains")
        if isinstance(tc, list):
            toks += tc
        elif isinstance(tc, str):
            toks += [tc]
        toks += list(exp.get("any_text_contains") or [])
        # Light tokenisation: split on spaces
        toks = [t for t in toks if t]
        return sum(1 for t in toks if _contains(carrier, t))

    msgs: List[str] = []
    for idx, eb in enumerate(exp_blocks or []):
        if any(_block_matches(eb, ab) for ab in (act_blocks or [])):
            continue
        # not matched; suggest nearest candidates
        scored: List[Tuple[int, str]] = []
        for ab in (act_blocks or []):
            c = _text_carrier(ab)
            scored.append((score(eb, c), c[:240]))
        scored.sort(key=lambda x: x[0], reverse=True)
        best = "\n    ".join([f"• [{s}] {c}" for s, c in scored[:top_k]])
        msgs.append(
            f"- Unmet expectation #{idx+1}: {eb}\n  Closest blocks:\n    {best or '• (no blocks)'}"
        )
    return msgs
