from __future__ import annotations

import re
from typing import Dict, List, Tuple, Optional

__all__ = ["process_section_blocks", "classify_section_blocks"]

# --- Line classifiers ---------------------------------------------------------

_BULLET_RE        = re.compile(r"^\s*[\*\-]\s+\S")  # "* Item" or "- Item"
_NUMBERED_RE      = re.compile(r"^\s*(?:\d+[\)\].]|[\[\(]\d+[\]\)])\s+\S")  # "1) x", "1. x", "[1] x", "(1) x"
# Pairs: "Label : value" or "Label - value"
_PAIR_RE          = re.compile(r"^\s*([^:\-][^:]{0,100}?)\s*(?::|-)\s*(\S.*\S|\S)\s*$")
# Subheading line used within GH text: "* Something :" (ends with a colon)
_SUBHEADING_RE    = re.compile(r"^\s*\*\s+.+:\s*$")
# Blank line
_BLANK_RE         = re.compile(r"^\s*$")
# Lines made only of hyphens → treat as a separator (no block emitted)
_ALL_HYPHENS_RE = re.compile(r"^\s*-+\s*$")
# Near-miss banners like "- Option Menu -" → we treat as subheadings
_NEAR_MISS_BANNER_RE = re.compile(r"^\s*-\s*([^-].*[^-])\s*-\s*$")
# Pairs strictly with spaced separators:
#   "Label : value"  or  "Label - value"
_PAIR_COLON_RE = re.compile(r"^\s*([^:]{1,100}?)\s*:\s+(\S.*\S|\S)\s*$")
_PAIR_DASH_RE  = re.compile(r"^\s*([^-]{1,100}?)\s+-\s+(\S.*\S|\S)\s*$")


def _inc_count(ps: Dict, kind: str) -> None:
    c = ps.setdefault("block_type_counts", {})
    c[kind] = int(c.get(kind, 0)) + 1

def _flush_paragraph(acc: List[str], out: List[dict], ps: Dict) -> None:
    if not acc:
        return
    text = " ".join(line.strip() for line in acc if line is not None).strip()
    if text:
        out.append({"type": "paragraph", "text": text})
        _inc_count(ps, "paragraph")
    acc.clear()

def process_section_blocks(
    *,
    primary: Optional[str],
    section_tag: str,
    lines: List[str],
    parsing_state: Dict
) -> List[dict]:
    """
    Convert raw section lines to structured blocks.

    For sections like 'overview' where GH commonly writes one paragraph per line
    (single newline between paragraphs, no blank separators), we force a
    'paragraph per line' policy to avoid coalescing unrelated paragraphs.

    Block types:
      - paragraph:     { "type": "paragraph", "text": "..." }
      - bullet_list:   { "type": "bullet_list", "items": [...] }
      - numbered_list: { "type": "numbered_list", "items": [...] }
      - pair:          { "type": "pair", "label": "...", "value": "..." }
      - subheading:    { "type": "subheading", "text": "..." }
      - unknown:       { "type": "unknown", "text": "..." }
    """
    blocks: List[dict] = []

    # --- policy: sections that should treat each non-blank line as its own paragraph
    FORCE_PARAGRAPH_PER_LINE = {"overview"}  # extend later if needed
    per_line = (section_tag or "").strip().lower() in FORCE_PARAGRAPH_PER_LINE

    # state for accumulating current multi-line paragraph or current list
    para_acc: List[str] = []
    list_acc: List[str] = []
    list_kind: Optional[str] = None  # "bullet_list" | "numbered_list" | None

    def flush_list():
        nonlocal list_acc, list_kind
        if list_kind and list_acc:
            blocks.append({"type": list_kind, "items": list_acc[:]})
            _inc_count(parsing_state, list_kind)
        list_acc = []
        list_kind = None

    for raw in lines:
        line = raw if raw is not None else ""

        # Blank line → ends paragraph and any open list
        if _BLANK_RE.match(line):
            _flush_paragraph(para_acc, blocks, parsing_state)
            flush_list()
            continue

        # Pure hyphen rules (if present in your file)
        if _ALL_HYPHENS_RE.match(line):
            _flush_paragraph(para_acc, blocks, parsing_state)
            flush_list()
            continue

        # Bullet list item
        if _BULLET_RE.match(line):
            _flush_paragraph(para_acc, blocks, parsing_state)
            if list_kind not in (None, "bullet_list"):
                flush_list()
            list_kind = "bullet_list"
            item = re.sub(r"^\s*[\*\-]\s+", "", line, count=1).strip()
            list_acc.append(item)
            continue

        # Numbered list item
        if _NUMBERED_RE.match(line):
            _flush_paragraph(para_acc, blocks, parsing_state)
            if list_kind not in (None, "numbered_list"):
                flush_list()
            list_kind = "numbered_list"
            item = re.sub(r"^\s*(?:\d+[\)\].]|[\[\(]\d+[\]\)])\s+", "", line, count=1).strip()
            list_acc.append(item)
            continue

        # Subheading lines (asterisk form)
        if _SUBHEADING_RE.match(line):
            _flush_paragraph(para_acc, blocks, parsing_state)
            flush_list()
            text = line.strip()
            text = re.sub(r"^\s*\*\s+", "", text, count=1)
            text = re.sub(r":\s*$", "", text, count=1)
            blocks.append({"type": "subheading", "text": text})
            _inc_count(parsing_state, "subheading")
            continue

        # Near-miss banner (e.g. "- Option Menu -") → treat as subheading (if you kept this regex)
        m_nm = _NEAR_MISS_BANNER_RE.match(line)
        if m_nm:
            content = m_nm.group(1).strip()
            if content and not re.fullmatch(r"-+", content):
                _flush_paragraph(para_acc, blocks, parsing_state)
                flush_list()
                blocks.append({"type": "subheading", "text": content})
                _inc_count(parsing_state, "subheading")
                continue
   
        # Pair detection: disable in per-line sections (e.g., overview) to avoid false positives,
        # and only accept spaced separators to avoid hyphenated words like "free-wheeling".
        if not per_line:
            m_pair = _PAIR_COLON_RE.match(line) or _PAIR_DASH_RE.match(line)
            if m_pair:
                _flush_paragraph(para_acc, blocks, parsing_state)
                flush_list()
                label = m_pair.group(1).strip()
                value = m_pair.group(2).strip()
                blocks.append({"type": "pair", "label": label, "value": value})
                _inc_count(parsing_state, "pair")
                continue

        # Otherwise, paragraph content
        flush_list()
        if per_line:
            # One paragraph per non-blank line
            blocks.append({"type": "paragraph", "text": line.strip()})
            _inc_count(parsing_state, "paragraph")
        else:
            # Accumulate until a delimiter (blank line, rule, or structural break)
            para_acc.append(line)

    # flush trailing accumulators
    _flush_paragraph(para_acc, blocks, parsing_state)
    if list_kind and list_acc:
        blocks.append({"type": list_kind, "items": list_acc[:]})
        _inc_count(parsing_state, list_kind)

    if not blocks and lines:
        blocks.append({"type": "unknown", "text": " ".join(l.strip() for l in lines).strip()})
        _inc_count(parsing_state, "unknown")

    return blocks

# --- Back-compat wrapper ------------------------------------------------------

def classify_section_blocks(
    section_name: str,
    lines: List[str],
    parsing_state: Dict,
    *,
    prefer_pairs: bool | None = None,
) -> List[Dict]:
    """
    Backwards-compatible wrapper for legacy callers.

    - 'section_name' is treated as the canonical section tag.
    - 'prefer_pairs' is ignored (the new engine auto-detects pairs vs paragraphs).
    """
    section_tag = (section_name or "").strip() or "unknown"
    # primary is unknown at this call site; it isn't required by the engine
    return process_section_blocks(primary=None, section_tag=section_tag, lines=lines, parsing_state=parsing_state)
