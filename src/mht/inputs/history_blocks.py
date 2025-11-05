from __future__ import annotations

import re
from typing import Dict, List, Tuple, Optional
import hashlib

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

# ---- Section policies --------------------------------------------------------
# Force or allow per-line paragraph mode on specific sections.
# - per_line=True: every non-blank line becomes its own paragraph block.
# - heuristic_per_line=True: if the section has no structural lines, use per-line mode.
# If a section tag is absent here, the default is heuristic_per_line=False, per_line=False.
SECTION_POLICIES = {
    "overview": {"per_line": True},
    "trivia":   {"per_line": True},       # was heuristic; now forced per-line
    "updates":  {"heuristic_per_line": True},
    "technical": {"per_line": False},
    "staff":     {"per_line": False},
    "series":    {"per_line": False},
    "scoring":   {"per_line": False},
}

def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:8]

def _policy_for(section_tag: str) -> dict:
    tag = (section_tag or "").strip().lower()
    return SECTION_POLICIES.get(tag, {})

def _is_structural_line(line: str) -> bool:
    """Return True if the line is a list item, pair, subheading or banner-like."""
    if _BLANK_RE.match(line):
        return False
    if _ALL_HYPHENS_RE.match(line):
        return True
    if _BULLET_RE.match(line) or _NUMBERED_RE.match(line):
        return True
    if _SUBHEADING_RE.match(line):
        return True
    if _NEAR_MISS_BANNER_RE.match(line):
        return True
    # use strict spaced separators only for pair detection here        
    if _PAIR_COLON_RE.match(line) or _PAIR_DASH_RE.match(line):
        return True
    return False

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
    parsing_state: Dict[str, Any],
    # NEW: provenance from suppressor (optional but recommended)
    filtered_to_raw: Optional[List[int]] = None,          # 1-based raw line number for each filtered line
    per_line_suppressions: Optional[Dict[int, List[str]]] = None,  # filtered idx -> suppression keys
) -> List[dict]:
    """
    Convert filtered section lines to structured blocks with provenance meta.

    Meta attached to each block:
      - system, section_tag, block_index (set later by caller)
      - raw_line_start/end (1-based), filtered_line_start/end (0-based indices)
      - policy (per_line / heuristic flags)
      - detectors (which rule produced this block)
      - suppressions (union of suppression keys seen in lines forming this block)
      - text_hash (short hash of emitted block text)
    """
    blocks: List[dict] = []
    tag = (section_tag or "").strip().lower()

    # --- Decide policy
    policy_cfg = SECTION_POLICIES.get(tag, {})
    forced_per_line = bool(policy_cfg.get("per_line"))
    allow_heuristic = bool(policy_cfg.get("heuristic_per_line"))

    non_blank = [ln for ln in lines if (ln or "").strip()]
    has_structural = any(_is_structural_line(ln) for ln in non_blank)
    dynamic_per_line = allow_heuristic and (not has_structural) and (len(non_blank) > 1)
    per_line = forced_per_line or dynamic_per_line

    # cursors for provenance across filtered lines
    # filtered_idx will be advanced as we consume lines into blocks
    filtered_idx = 0

    def _make_meta(detectors: List[str], f_start: int, f_end: int, text: str) -> dict:
        # f_start/f_end are filtered line indices (inclusive), 0-based
        # map to raw line numbers if available
        if filtered_to_raw and 0 <= f_start < len(filtered_to_raw) and 0 <= f_end < len(filtered_to_raw):
            r_start = filtered_to_raw[f_start]
            r_end   = filtered_to_raw[f_end]
        else:
            r_start = r_end = None

        # collect suppression keys seen in these filtered lines
        supp: List[str] = []
        if per_line_suppressions:
            for fi in range(f_start, f_end + 1):
                supp.extend(per_line_suppressions.get(fi, []))
        # dedupe and keep stable order
        seen = set()
        supp_unique = [s for s in supp if not (s in seen or seen.add(s))]

        return {
            "system": primary,
            "section_tag": tag,
            "block_index": None,   # filled by caller after block list is final
            "raw_line_start": r_start,
            "raw_line_end": r_end,
            "filtered_line_start": f_start,
            "filtered_line_end": f_end,
            "policy": {
                "per_line": per_line,
                "heuristic_per_line": bool(dynamic_per_line),
            },
            "detectors": detectors,
            "suppressions": supp_unique,
            "text_hash": _short_hash(text or ""),
        }

    # list accumulation state
    list_acc: List[str] = []
    list_kind: Optional[str] = None

    def flush_list():
        nonlocal list_acc, list_kind, filtered_idx
        if list_kind and list_acc:
            start = filtered_idx - len(list_acc)
            end   = filtered_idx - 1
            meta = _make_meta(
                detectors=[ "bullet_asterisk" if list_kind == "bullet_list" else "numbered_1)" ],
                f_start=start, f_end=end,
                text="\n".join(list_acc)
            )
            blocks.append({ "type": list_kind, "items": list_acc[:], "meta": meta })
            _inc_count(parsing_state, list_kind)
        list_acc = []
        list_kind = None

    # paragraph accumulator for normal mode
    para_acc: List[str] = []
    para_start_idx: Optional[int] = None

    def flush_para(detector_label: str):
        nonlocal para_acc, para_start_idx, filtered_idx
        if para_acc:
            start = para_start_idx if para_start_idx is not None else filtered_idx - len(para_acc)
            end   = filtered_idx - 1
            text  = "\n".join(para_acc).strip()
            if text:
                meta = _make_meta(detectors=[detector_label], f_start=start, f_end=end, text=text)
                blocks.append({ "type": "paragraph", "text": text, "meta": meta })
                _inc_count(parsing_state, "paragraph")
        para_acc = []
        para_start_idx = None

    # --- main loop over filtered lines
    for line in lines:
        ln = (line or "")

        # blank line → block separators
        if _BLANK_RE.match(ln):
            flush_para("paragraph_default")
            flush_list()
            filtered_idx += 1
            continue

        # pure hyphen rule → also a separator
        if _ALL_HYPHENS_RE.match(ln):
            flush_para("paragraph_default")
            flush_list()
            filtered_idx += 1
            continue

        # bullets
        if _BULLET_RE.match(ln):
            flush_para("paragraph_default")
            if list_kind not in (None, "bullet_list"):
                flush_list()
            list_kind = "bullet_list"
            item = re.sub(r"^\s*[\*\-]\s+", "", ln, count=1).strip()
            list_acc.append(item)
            filtered_idx += 1
            continue

        # numbered
        if _NUMBERED_RE.match(ln):
            flush_para("paragraph_default")
            if list_kind not in (None, "numbered_list"):
                flush_list()
            list_kind = "numbered_list"
            item = re.sub(r"^\s*(?:\d+[\)\].]|[\[\(]\d+[\]\)])\s+", "", ln, count=1).strip()
            list_acc.append(item)
            filtered_idx += 1
            continue

        # subheading
        if _SUBHEADING_RE.match(ln):
            flush_para("paragraph_default")
            flush_list()
            text = ln.strip()
            text = re.sub(r"^\s*\*\s+", "", text, count=1)
            text = re.sub(r":\s*$", "", text, count=1)
            meta = _make_meta(detectors=["subheading_star_colon"], f_start=filtered_idx, f_end=filtered_idx, text=text)
            blocks.append({ "type": "subheading", "text": text, "meta": meta })
            _inc_count(parsing_state, "subheading")
            filtered_idx += 1
            continue

        # near-miss banner -> treat as subheading
        m_nm = _NEAR_MISS_BANNER_RE.match(ln)
        if m_nm:
            flush_para("paragraph_default")
            flush_list()
            content = m_nm.group(1).strip()
            if content and not re.fullmatch(r"-+", content):
                meta = _make_meta(detectors=["near_miss_banner"], f_start=filtered_idx, f_end=filtered_idx, text=content)
                blocks.append({ "type": "subheading", "text": content, "meta": meta })
                _inc_count(parsing_state, "subheading")
                filtered_idx += 1
                continue

        # pairs: only in normal mode (not per-line)
        if not per_line:
            m_pair = _PAIR_COLON_RE.match(ln) or _PAIR_DASH_RE.match(ln)
            if m_pair:
                flush_para("paragraph_default")
                flush_list()
                label = m_pair.group(1).strip()
                value = m_pair.group(2).strip()
                text = f"{label}: {value}"
                meta = _make_meta(detectors=["pair_colon" if ":" in ln else "pair_dash"],
                                  f_start=filtered_idx, f_end=filtered_idx, text=text)
                blocks.append({ "type": "pair", "label": label, "value": value, "meta": meta })
                _inc_count(parsing_state, "pair")
                filtered_idx += 1
                continue

        # narrative text
        if per_line:
            flush_list()
            text = ln.strip()
            if text:
                meta = _make_meta(detectors=["paragraph_per_line"], f_start=filtered_idx, f_end=filtered_idx, text=text)
                blocks.append({ "type": "paragraph", "text": text, "meta": meta })
                _inc_count(parsing_state, "paragraph")
            filtered_idx += 1
        else:
            if para_start_idx is None:
                para_start_idx = filtered_idx
            para_acc.append(ln)
            filtered_idx += 1

    # tail flush
    flush_para("paragraph_default")
    flush_list()

    # note: block_index/system/section_tag finalisation is done by the caller
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
