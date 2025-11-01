from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional

__all__ = ["classify_section_blocks"]

# --- Line-shape detectors -----------------------------------------------------

# Subheading: leading asterisk, ends with a colon
_SUBHEADING_RE = re.compile(r"^\*\s+(.+?):\s*$")

# Bullets: leading '* ' or '- ' (but not subheading)
_BULLET_RE = re.compile(r"^(?:\*|-)\s+.+?$")

# Numbered: 1) text   or   [1] text   or   1. text
_NUMBERED_RE = re.compile(r"^(?:\d+\)|\[\d+\]|\d+\.)\s+.+?$")

# Pair with colon: Key: Value   — avoid trivial or trailing-colon only
# Heuristic: short-ish key on the left, at least 2 chars on right
_PAIR_COLON_RE = re.compile(r"^(.{1,48}?)\s*:\s*(.{2,})$")

# Pair with dash:  Left - Right     — allow quotes and brackets on either side
# Used for lines like 'Speedy - "Pinky" (pink ghost)'
_PAIR_DASH_RE = re.compile(r"^(.{1,48}?)\s-\s(.{2,})$")

# Non-content separators or noise to ignore when grouping paragraphs
_EMPTY_RE = re.compile(r"^\s*$")


# --- Helpers ------------------------------------------------------------------

def _is_subheading(line: str) -> Optional[str]:
    m = _SUBHEADING_RE.match(line)
    return m.group(1).strip() if m else None

def _is_bullet(line: str) -> bool:
    # Note: subheadings also begin with '* ', so check subheading first in the caller
    return bool(_BULLET_RE.match(line))

def _is_numbered(line: str) -> bool:
    return bool(_NUMBERED_RE.match(line))

def _is_pair(line: str) -> Optional[dict]:
    """
    Return a pair dict if line looks like a key:value or key - value,
    else None. Keys are trimmed of trailing punctuation.
    """
    m = _PAIR_COLON_RE.match(line)
    if m:
        key = m.group(1).strip().rstrip("：:")  # handle normal and full-width just in case
        val = m.group(2).strip()
        if key and val:
            return {"sep": ":", "key": key, "value": val}

    m = _PAIR_DASH_RE.match(line)
    if m:
        key = m.group(1).strip()
        val = m.group(2).strip()
        if key and val:
            return {"sep": "-", "key": key, "value": val}

    return None


# --- Core classifier ----------------------------------------------------------

def classify_section_blocks(
    section_name: str,
    lines: List[str],
    parsing_state: Dict,
    *,
    prefer_pairs: bool | None = None,
) -> List[Dict]:
    """
    Classify a list of text lines for a single GH section into structured blocks.

    Parameters
    ----------
    section_name : str
        Canonical section name, e.g. 'TRIVIA', 'STAFF', 'TECHNICAL', 'SCORING'.
    lines : List[str]
        Section content as individual lines (not a single joined string).
    parsing_state : Dict
        Mutable shared dict; this function increments:
          - parsing_state['block_type_counts'] : Counter
          - parsing_state['unknown_blocks']    : {section: [lines]}
    prefer_pairs : Optional[bool]
        If True, slightly biases ambiguous lines towards 'pair' classification.
        Default:
            - STAFF, SCORING: True
            - otherwise: False

    Returns
    -------
    List[Dict]
        Each block is a dict with at least:
            {
              "type": "subheading"|"bullet_list"|"numbered_list"|"pair"|"paragraph"|"unknown",
              "text": "..."                          # for paragraph, subheading, unknown
              "items": ["...", "..."]                # for bullet_list, numbered_list
              "pairs": [{"key": "...", "value": "..."}]  # for pair (possibly aggregated)
            }
        Blocks preserve input order, and consecutive lines of the same kind are grouped.
    """
    # Policy: which sections are pair-heavy by default
    if prefer_pairs is None:
        prefer_pairs = section_name in {"STAFF", "SCORING"}

    blocks: List[Dict] = []
    add_count = parsing_state.setdefault("block_type_counts", Counter()).update
    unknown_map = parsing_state.setdefault("unknown_blocks", {})

    # Groupers for bullets, numbers, and pairs
    current_bullets: Optional[List[str]] = None
    current_numbers: Optional[List[str]] = None
    current_pairs: Optional[List[dict]] = None

    def flush_lists():
        nonlocal current_bullets, current_numbers, current_pairs
        if current_bullets:
            blocks.append({"type": "bullet_list", "items": current_bullets})
            add_count(["bullet_list"])
            current_bullets = None
        if current_numbers:
            blocks.append({"type": "numbered_list", "items": current_numbers})
            add_count(["numbered_list"])
            current_numbers = None
        if current_pairs:
            blocks.append({"type": "pair", "pairs": current_pairs})
            add_count(["pair"])
            current_pairs = None

    def append_paragraph(text: str):
        # Merge with previous paragraph if adjacent
        if blocks and blocks[-1]["type"] == "paragraph":
            prev = blocks[-1]
            prev["text"] = prev["text"] + "\n" + text
        else:
            blocks.append({"type": "paragraph", "text": text})
            add_count(["paragraph"])

    for raw in lines:
        line = (raw or "").rstrip()

        # Section-specific: allow empty lines to terminate current grouped blocks
        if _EMPTY_RE.match(line):
            flush_lists()
            # Paragraphs are allowed to span across blank lines? No — keep it simple for now.
            continue

        # Subheading
        sub = _is_subheading(line)
        if sub is not None:
            flush_lists()
            blocks.append({"type": "subheading", "text": sub})
            add_count(["subheading"])
            continue

        # Bullets and numbered lists
        if _is_bullet(line):
            # Safety: ignore if it was a subheading (already handled)
            if current_numbers:
                # switching list types
                flush_lists()
            if current_bullets is None:
                current_bullets = []
            # strip marker
            current_bullets.append(line[2:].strip())
            continue

        if _is_numbered(line):
            if current_bullets:
                flush_lists()
            if current_numbers is None:
                current_numbers = []
            # normalise: keep the whole text after the marker
            txt = line
            # strip common patterns
            if ")" in txt.split(" ", 1)[0]:
                txt = txt.split(")", 1)[1].lstrip()
            elif "." in txt.split(" ", 1)[0]:
                txt = txt.split(".", 1)[1].lstrip()
            elif txt.startswith("[") and "]" in txt:
                txt = txt.split("]", 1)[1].lstrip()
            current_numbers.append(txt)
            continue

        # Pair detection. If prefer_pairs, try this before paragraph fallback.
        pair = _is_pair(line) if prefer_pairs else None
        if pair:
            if current_pairs is None:
                current_pairs = []
            current_pairs.append({"key": pair["key"], "value": pair["value"]})
            continue

        # If not pair first, we can still treat obvious pairs even when prefer_pairs is False
        if not prefer_pairs:
            pair = _is_pair(line)
            if pair:
                if current_pairs is None:
                    current_pairs = []
                current_pairs.append({"key": pair["key"], "value": pair["value"]})
                continue

        # Anything else: paragraph by default
        flush_lists()
        # Light normalisation: avoid lone trailing colons being treated as paragraphs-with-intent
        append_paragraph(line)

    # Flush any trailing grouped content
    flush_lists()

    # Record unknowns for QA - in this first pass we only treat lines as unknown
    # if they resulted in no blocks at all. Later we can add finer-grained unknowns.
    if not blocks:
        unknown_map.setdefault(section_name, []).extend(lines)
        add_count(["unknown"])
        blocks.append({"type": "unknown", "text": "\n".join(lines)})

    return blocks
