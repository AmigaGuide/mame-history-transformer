from __future__ import annotations

import re
from typing import Any, Dict, List

__all__ = ["blocks_satisfy_expectations"]


# ---------------------------------------------------------------------------
# Helpers to normalise block text
# ---------------------------------------------------------------------------

def _text_carrier(block: Dict[str, Any]) -> str:
    """
    Return a unified text 'haystack' for this block so expectations can
    search within a single string.

    - paragraph / subheading: use `text`
    - bullet_list / numbered_list: join `items` with newlines
    - pair: "label: value"
    - otherwise: try any obvious textual fields, or return "".
    """
    if not isinstance(block, dict):
        return ""

    btype = block.get("type")

    if btype in ("paragraph", "subheading"):
        return str(block.get("text") or "")

    if btype in ("bullet_list", "numbered_list"):
        items = block.get("items") or []
        if isinstance(items, list):
            return "\n".join(str(it) for it in items)
        return str(items)

    if btype == "pair":
        label = str(block.get("label") or "")
        value = str(block.get("value") or "")
        text = f"{label}: {value}".strip()
        return text

    # Fallback: concatenate any known textual fields if present
    parts: list[str] = []
    for key in ("text", "label", "value"):
        v = block.get(key)
        if isinstance(v, str) and v:
            parts.append(v)
    return " ".join(parts) if parts else ""


def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    try:
        return [str(x) for x in v]
    except TypeError:
        return [str(v)]


def _words(s: str) -> list[str]:
    """Normalise a string into lowercase 'word' tokens."""
    return re.findall(r"\w+", s.lower())


# ---------------------------------------------------------------------------
# Generic text matcher used by all block types
# ---------------------------------------------------------------------------

def _match_text_expectation(exp_block: Dict[str, Any], carrier: str) -> bool:
    """
    Generic text-based matcher against a single 'carrier' string.

    Supports:
      - text_contains: str OR [str,...]   (ALL must be substrings, with
                                           word-based fallback)
      - any_text_contains: [str,...]      (AT LEAST ONE must be a substring
                                           or word-based match)
      - text_regex: regex pattern         (must search-match)
    """
    haystack = carrier or ""

    # text_regex (if present)
    pattern = exp_block.get("text_regex")
    if pattern:
        try:
            regex = re.compile(pattern)
        except re.error:
            # Treat invalid regex as non-match rather than raising
            return False
        if not regex.search(haystack):
            return False

    # Helper for substring OR word-based match
    def _text_match(frag: str) -> bool:
        if not frag:
            return True
        if frag in haystack:
            return True
        exp_words = _words(frag)
        hay_words = set(_words(haystack))
        return all(w in hay_words for w in exp_words)

    # text_contains: require ALL fragments to match
    tc = exp_block.get("text_contains")
    for frag in _as_list(tc):
        if frag and not _text_match(frag):
            return False

    # any_text_contains: require at least ONE to match
    atc = exp_block.get("any_text_contains")
    if atc:
        candidates = _as_list(atc)
        if not any(frag and _text_match(frag) for frag in candidates):
            return False

    # If none of the above keys were provided, this is a pure type/meta-only match
    if not any(k in exp_block for k in ("text_contains", "any_text_contains", "text_regex")):
        return True

    return True


# ---------------------------------------------------------------------------
# Core expectation matcher
# ---------------------------------------------------------------------------

def _block_matches_expectation(exp_block: dict, act_block: dict) -> bool:
    """
    Return True if a single actual block satisfies a single expectation block.

    Rules:
      - 'type' is enforced for list/subheading/pair expectations, but relaxed
        for 'paragraph' expectations and for meta_preamble_for_list expectations.
      - 'text_contains' must match either as a direct substring OR via
        a word-based match (ignoring punctuation / case).
      - 'value_contains' on list blocks must match at least one list item.
      - For 'pair' blocks, 'label_contains'/'key_contains' and 'value_contains'
        apply to the label and value respectively.
      - 'meta_preamble_for_list': if True, we *prefer* blocks that actually
        have meta['preamble_for_list'] == True, but we do NOT fail if the
        key is missing; we only reject blocks where it is explicitly False.
    """
    if not isinstance(act_block, dict):
        return False

    exp_type = exp_block.get("type")
    act_type = act_block.get("type")
    meta = act_block.get("meta", {}) or {}

    # Decide whether to relax type matching
    relax_type = False
    if exp_type == "paragraph":
        relax_type = True
    if exp_block.get("meta_preamble_for_list"):
        relax_type = True

    # Strict type enforcement unless relaxed
    if exp_type and not relax_type and act_type != exp_type:
        return False

    # Soft check for meta_preamble_for_list
    if exp_block.get("meta_preamble_for_list"):
        # If the block explicitly says "I am NOT a preamble", reject it.
        # If the flag is missing, we allow it.
        if "preamble_for_list" in meta and not meta.get("preamble_for_list"):
            return False

    # Special handling for 'pair' blocks (label/value semantics)
    if act_type == "pair":
        label = str(act_block.get("label") or "")
        value = str(act_block.get("value") or "")

        label_contains = exp_block.get("label_contains") or exp_block.get("key_contains")
        if label_contains:
            for frag in _as_list(label_contains):
                if frag and frag not in label:
                    return False

        val_contains = exp_block.get("value_contains")
        if val_contains:
            for frag in _as_list(val_contains):
                if frag and frag not in value:
                    return False

    # value_contains for list blocks (bullet_list / numbered_list)
    val_contains = exp_block.get("value_contains")
    if val_contains and act_type in ("bullet_list", "numbered_list"):
        items = act_block.get("items") or []
        combined = "\n".join(str(s) for s in items)
        for frag in _as_list(val_contains):
            if frag and frag not in combined:
                return False

    # Generic text-based expectations against a 'carrier' string
    carrier = _text_carrier(act_block)

    if not _match_text_expectation(exp_block, carrier):
        return False

    return True


# ---------------------------------------------------------------------------
# Public API used by tests
# ---------------------------------------------------------------------------

def blocks_satisfy_expectations(exp_blocks, act_blocks) -> bool:
    """
    For each expectation in exp_blocks, ensure that there is at least one
    actual block in act_blocks that satisfies it.

    This is a *subset existence* check, not an ordering check.
    """
    for idx, exp in enumerate(exp_blocks):
        matched = any(_block_matches_expectation(exp, cand) for cand in act_blocks)

        if not matched:
            # Debug output
            exp_type = exp.get("type")
            print("[blocks_satisfy_expectations] FAILED expectation:")
            print(f"  expectation #{idx}: {exp!r}")
            if exp_type:
                print(f"  expected type={exp_type!r}")
            if "text_contains" in exp:
                print(f"  expected text fragment={exp.get('text_contains')!r}")
            if "value_contains" in exp:
                print(f"  expected value fragment={exp.get('value_contains')!r}")
            if "meta_preamble_for_list" in exp:
                print(f"  expected meta_preamble_for_list={exp.get('meta_preamble_for_list')!r}")
            print(f"  candidate blocks (all types):")
            for i, cand in enumerate(act_blocks):
                print(f"    candidate[{i}]: {cand!r}")
            return False

    return True
