from __future__ import annotations

import re
from typing import Dict, List, Optional, Any
import hashlib

__all__ = [
    "process_section_blocks",
    "classify_section_blocks",
    "attach_list_preambles",
    "flag_suspect_hard_wraps",
    "schema_sanitize_blocks",
    "promote_preamble_paragraphs_to_bullet_lists",
]

# --- Line classifiers ---------------------------------------------------------

_BULLET_RE        = re.compile(r"^\s*[\*\-]\s+\S")  # "* Item" or "- Item"
_NUMBERED_RE      = re.compile(r"^\s*(?:\d+[\)\].]|[\[\(]\d+[\]\)])\s+\S")  # "1) x", "1. x", "[1] x", "(1) x"
# Pairs: "Label : value" or "Label - value"
_PAIR_RE          = re.compile(r"^\s*([^:\-][^:]{0,100}?)\s*(?::|-)\s*(\S.*\S|\S)\s*$")
# Subheading line used within GH text: "* Something :" (ends with a colon)
_SUBHEADING_RE    = re.compile(r"^\s*\*\s+.+:\s*$")
# GH Staff sometimes uses Markdown-style emphasis around labels.
# These patterns are deliberately restricted to Staff by their caller.
_STAFF_EMPHASISED_PAIR_RE = re.compile(
    r"^\s*\*([^*\n]+)\*\s*:\s*(\S.*)$"
)
_STAFF_EMPHASISED_HEADING_RE = re.compile(
    r"^\s*\*([^*\n]+)\*\s*$"
)
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
# Standalone all-caps heading, optionally ending with a colon, e.g. "ADDITIONAL NOTES" or "ADDITIONAL NOTES:"
_UPPER_HEADING_RE = re.compile(r"^[A-Z0-9][A-Z0-9 \-&'/]+:?$")


_LIST_TYPES = {"bullet_list", "numbered_list"}

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

# Allowed meta keys per trivia schema# Allowed meta keys per trivia schema (keep in sync with tests/schema)
ALLOWED_META_KEYS = {
    "system", "section_tag", "block_index",
    "raw_line_start", "raw_line_end",
    "filtered_line_start", "filtered_line_end",
    "policy", "detectors", "suppressions", "text_hash",
}

# Only these keys are permitted inside meta.policy by the schema
ALLOWED_POLICY_KEYS = {"per_line", "heuristic_per_line"}

def _split_pair_line(ln: str) -> tuple[str, str, str] | None:
    """
    Try to split a line into (kind, label, value) where kind is
    'pair_colon' or 'pair_dash', only using separators that are
    *outside* any parentheses/brackets.

    Returns None if the line shouldn't be treated as a pair.
    """
    if not ln:
        return None

    s = ln.rstrip("\n")
    paren_depth = 0
    bracket_depth = 0

    colon_pos: int | None = None
    dash_pos: int | None = None

    # First pass: find candidate ':' and ' - ' positions at top level
    i = 0
    while i < len(s):
        ch = s[i]

        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)

        # candidate ':' (only if not nested)
        if ch == ":" and paren_depth == 0 and bracket_depth == 0 and colon_pos is None:
            colon_pos = i

        # candidate " - " (only if not nested)
        if ch == "-" and paren_depth == 0 and bracket_depth == 0 and dash_pos is None:
            # require spaces around the dash to reduce false positives
            if i > 0 and i < len(s) - 1 and s[i - 1].isspace() and s[i + 1].isspace():
                dash_pos = i

        i += 1

    # Prefer whichever valid separator occurs first in the string
    sep_kind: str | None = None
    sep_index: int | None = None

    def _better(a: int | None, b: int | None) -> int | None:
        if a is None:
            return b
        if b is None:
            return a
        return a if a < b else b

    first_colon = colon_pos
    first_dash = dash_pos
    first_any = _better(first_colon, first_dash)

    if first_any is None:
        return None  # no usable separator at top level

    if first_any == first_colon:
        sep_kind = "pair_colon"
        sep_index = first_colon
    else:
        sep_kind = "pair_dash"
        sep_index = first_dash

    # Split into label/value and enforce basic sanity
    assert sep_kind is not None and sep_index is not None
    label_raw = s[:sep_index].rstrip()
    value_raw = s[sep_index + 1 :].lstrip()  # +1: skip ':' or '-'

    # For colon we expect "label : value" so skip extra spaces after colon;
    # for dash we already required spaces around it.
    if sep_kind == "pair_colon" and value_raw.startswith(" "):
        value_raw = value_raw.lstrip()

    label = label_raw.strip()
    value = value_raw.strip()

    if not label or not value:
        return None
    if len(label) > 100:
        return None

    return sep_kind, label, value

def schema_sanitize_blocks(blocks: list[dict]) -> list[dict]:
    """
    Enforce a minimal, schema-safe block shape while preserving analysis metadata
    we rely on (preamble annotations, detectors, etc.), and *deep-sanitise* meta.policy
    so it only includes keys allowed by the schema.
    """
    if not isinstance(blocks, list):
        return []

    ALLOWED_BY_TYPE = {
        "paragraph": {"type", "text", "meta"},
        "bullet_list": {"type", "items", "meta"},
        "numbered_list": {"type", "items", "meta"},
        "pair": {"type", "label", "value", "meta"},
        "subheading": {"type", "text", "meta"},
    }

    META_WHITELIST = {
        # provenance / indices
        "system", "section_tag", "block_index",
        "raw_line_start", "raw_line_end",
        "filtered_line_start", "filtered_line_end",
        # policy / detectors / trace
        "policy", "detectors", "suppressions", "text_hash",
        # preamble annotations
        "preamble_for_list", "preamble_target_index", "preamble_text",
    }

    # Only these keys may live under meta.policy per schema
    POLICY_WHITELIST = {"per_line", "heuristic_per_line"}

    sanitized: list[dict] = []

    for b in blocks:
        if not isinstance(b, dict):
            continue

        btype = b.get("type")
        if btype not in ALLOWED_BY_TYPE:
            continue

        keep_keys = ALLOWED_BY_TYPE[btype]
        nb = {k: v for k, v in b.items() if k in keep_keys}

        # Shape guards
        if btype == "paragraph":
            if not isinstance(nb.get("text"), str) or not nb["text"]:
                continue
        elif btype in ("bullet_list", "numbered_list"):
            items = nb.get("items")
            if not isinstance(items, list) or not items:
                continue
        elif btype == "pair":
            if not (isinstance(nb.get("label"), str) and isinstance(nb.get("value"), str)):
                continue

        # Meta sanitisation (whitelist + deep-clean policy)
        meta = nb.get("meta") or {}
        if isinstance(meta, dict):
            # keep only whitelisted meta keys
            meta_out = {k: v for k, v in meta.items() if k in META_WHITELIST}

            # ensure detectors is a list if present (and non-empty to satisfy schema)
            if "detectors" in meta_out:
                det = meta_out["detectors"]
                if not isinstance(det, list) or not det:
                    # reinitialise to a minimal detector if upstream forgot to set it
                    meta_out["detectors"] = ["paragraph_per_line"] if btype == "paragraph" else ["list_classifier"]

            # deep-sanitise policy to allowed keys only
            if "policy" in meta_out:
                pol = meta_out["policy"]
                if isinstance(pol, dict):
                    meta_out["policy"] = {k: bool(pol.get(k)) for k in POLICY_WHITELIST}
                else:
                    meta_out["policy"] = {k: False for k in POLICY_WHITELIST}

            nb["meta"] = meta_out
        else:
            nb["meta"] = {
                "system": "",
                "section_tag": "",
                "block_index": 0,
                "filtered_line_start": 0,
                "filtered_line_end": 0,
                "policy": {"per_line": False, "heuristic_per_line": False},
                "detectors": ["paragraph_per_line"] if btype == "paragraph" else ["list_classifier"],
                "suppressions": [],
                "text_hash": "00000000",
            }

        sanitized.append(nb)

    return sanitized

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
    # use the same top-level separator logic as pair splitting
    if _split_pair_line(line) is not None:
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

    # --- Record policy usage for summary (per section call)
    ppc = parsing_state.setdefault("provenance_policy_counts", {})
    sec = ppc.setdefault(tag, {"per_line": 0, "heuristic_per_line": 0})
    if per_line:
        sec["per_line"] += 1
    if dynamic_per_line:
        sec["heuristic_per_line"] += 1

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

        # --- Record blocks that carry suppressions (for summary)
        if supp_unique:
            parsing_state["provenance_blocks_with_suppressions"] = int(
                parsing_state.get("provenance_blocks_with_suppressions", 0)
            ) + 1

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

    # List accumulation state.
    #
    # A list item may span several physical GH source lines.
    # Track its actual line range rather than deriving that range
    # from the number of accumulated list items.
    list_acc: List[str] = []
    list_kind: Optional[str] = None
    list_start_idx: Optional[int] = None
    list_last_idx: Optional[int] = None

    def flush_list():
        nonlocal list_acc, list_kind, list_start_idx, list_last_idx

        if list_kind and list_acc:
            assert list_start_idx is not None
            assert list_last_idx is not None

            meta = _make_meta(
                detectors=[
                    "bullet_asterisk"
                    if list_kind == "bullet_list"
                    else "numbered_1)"
                ],
                f_start=list_start_idx,
                f_end=list_last_idx,
                text="\n".join(list_acc),
            )

            blocks.append({
                "type": list_kind,
                "items": list_acc[:],
                "meta": meta,
            })

            _inc_count(parsing_state, list_kind)

        list_acc = []
        list_kind = None
        list_start_idx = None
        list_last_idx = None

    # paragraph accumulator for normal mode
    para_acc: List[str] = []
    para_start_idx: Optional[int] = None

    def flush_para(detector_label: str):
        nonlocal para_acc, para_start_idx
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

    # Identify repeated Overview topic groups before classification.
    #
    # GH sometimes introduces several named topics with a paragraph
    # ending in a colon. Each marked topic contains its title and
    # initial description on one line, followed by unmarked prose.
    #
    # Require at least two consecutive topic groups. An isolated
    # colon-bearing bullet is not sufficient evidence of a heading.
    overview_named_topic_lines = set()

    if tag == "overview":
        topic_pattern = re.compile(
            r"^\s*\*\s+([^:]{1,60}?)\s*:\s+(\S.*)$"
        )

        for intro_idx, intro_line in enumerate(lines):
            intro_text = (intro_line or "").strip()

            if (
                not intro_text.endswith(":")
                or intro_text.startswith(("*", "-"))
            ):
                continue

            group_indices = []
            next_idx = intro_idx + 1

            # Topic groups must be separated from their introduction.
            while (
                next_idx < len(lines)
                and _BLANK_RE.match(lines[next_idx] or "")
            ):
                next_idx += 1

            if next_idx == intro_idx + 1:
                continue

            while next_idx < len(lines):
                match = topic_pattern.match(lines[next_idx] or "")

                if not match:
                    break

                title = match.group(1).strip()

                if len(title.split()) > 9:
                    break

                description_idx = next_idx + 1

                # Require at least one separate descriptive line.
                if (
                    description_idx >= len(lines)
                    or _is_structural_line(lines[description_idx] or "")
                    or _BLANK_RE.match(lines[description_idx] or "")
                ):
                    break

                # Find the end of this topic's descriptive group.
                while description_idx < len(lines):
                    following = lines[description_idx] or ""

                    if (
                        _BLANK_RE.match(following)
                        or _is_structural_line(following)
                    ):
                        break

                    description_idx += 1

                group_indices.append(next_idx)

                # The next topic must follow a blank-line boundary.
                if (
                    description_idx >= len(lines)
                    or not _BLANK_RE.match(
                        lines[description_idx] or ""
                    )
                ):
                    break

                next_idx = description_idx

                while (
                    next_idx < len(lines)
                    and _BLANK_RE.match(lines[next_idx] or "")
                ):
                    next_idx += 1

            if len(group_indices) >= 2:
                overview_named_topic_lines.update(group_indices)

    # Tips and Tricks may contain repeated named topics without an
    # introductory paragraph. Each topic begins with a marked
    # "Title : description" line, and blank lines separate topics.
    #
    # Require at least two consecutive qualifying groups. Preserve
    # unmarked descriptive lines for individual paragraph handling.
    # Isolated colon-bearing bullets remain ordinary list items.
    tips_named_topic_lines = set()
    tips_named_topic_description_lines = set()

    if tag == "tips and tricks":
        tips_topic_pattern = re.compile(
            r"^\s*\*\s+([^:]{1,60}?)\s*:\s+(\S.*)$"
        )

        groups = []
        scan_idx = 0

        while scan_idx < len(lines):
            if _BLANK_RE.match(lines[scan_idx] or ""):
                scan_idx += 1
                continue

            group_start = scan_idx

            while (
                scan_idx < len(lines)
                and not _BLANK_RE.match(lines[scan_idx] or "")
            ):
                scan_idx += 1

            group_end = scan_idx
            match = tips_topic_pattern.match(
                lines[group_start] or ""
            )

            valid = bool(
                match
                and len(match.group(1).strip().split()) <= 9
            )

            # A named topic may contain paragraphs and numbered lists.
            # These belong to the topic body and must not disqualify
            # the heading.
            #
            # Another marked bullet or a separator within the same
            # group makes its boundaries ambiguous.
            for idx in range(group_start + 1, group_end):
                following = lines[idx] or ""

                if (
                    _BULLET_RE.match(following)
                    or _ALL_HYPHENS_RE.match(following)
                ):
                    valid = False
                    break

            if valid:
                description_indices = [
                    idx
                    for idx in range(group_start + 1, group_end)
                    if (
                        not _NUMBERED_RE.match(lines[idx] or "")
                        and not _is_structural_line(lines[idx] or "")
                    )
                ]

                groups.append((
                    group_start,
                    description_indices,
                ))
            else:
                groups.append(None)

        consecutive = []

        # A non-qualifying group breaks the sequence of named topics.
        for group in groups + [None]:
            if group is not None:
                consecutive.append(group)
                continue

            if len(consecutive) >= 2:
                for heading_idx, description_indices in consecutive:
                    tips_named_topic_lines.add(heading_idx)
                    tips_named_topic_description_lines.update(
                        description_indices
                    )

            consecutive = []

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

        # Tips and Tricks named topics use the same title-description
        # convention as Overview, but do not require an introduction.
        #
        # Both emitted blocks retain the same physical source line.
        if (
            tag == "tips and tricks"
            and filtered_idx in tips_named_topic_lines
        ):
            match = tips_topic_pattern.match(ln)

            if match:
                title = match.group(1).strip()
                description = match.group(2).strip()

                description = (
                    description[0].upper() + description[1:]
                )

                flush_para("paragraph_default")
                flush_list()

                heading_meta = _make_meta(
                    detectors=["subheading_tips_named_topic"],
                    f_start=filtered_idx,
                    f_end=filtered_idx,
                    text=title,
                )

                blocks.append({
                    "type": "subheading",
                    "text": title,
                    "meta": heading_meta,
                })

                _inc_count(parsing_state, "subheading")

                paragraph_meta = _make_meta(
                    detectors=["paragraph_tips_named_topic"],
                    f_start=filtered_idx,
                    f_end=filtered_idx,
                    text=description,
                )

                blocks.append({
                    "type": "paragraph",
                    "text": description,
                    "meta": paragraph_meta,
                })

                _inc_count(parsing_state, "paragraph")

                filtered_idx += 1
                continue

        # GH Staff sometimes uses asterisks to emphasise role labels
        # and standalone group headings.
        #
        # Interpret these as existing pair/subheading block types.
        # The original source text remains unchanged in sections_raw.
        if tag == "staff":
            staff_pair = _STAFF_EMPHASISED_PAIR_RE.match(ln)

            if staff_pair:
                flush_para("paragraph_default")
                flush_list()

                label = staff_pair.group(1).strip()
                value = staff_pair.group(2).strip()
                text = f"{label}: {value}"

                meta = _make_meta(
                    detectors=["pair_staff_emphasis"],
                    f_start=filtered_idx,
                    f_end=filtered_idx,
                    text=text,
                )

                blocks.append({
                    "type": "pair",
                    "label": label,
                    "value": value,
                    "meta": meta,
                })

                _inc_count(parsing_state, "pair")
                filtered_idx += 1
                continue

            staff_heading = _STAFF_EMPHASISED_HEADING_RE.match(ln)

            if staff_heading:
                flush_para("paragraph_default")
                flush_list()

                heading = staff_heading.group(1).strip()

                meta = _make_meta(
                    detectors=["subheading_staff_emphasis"],
                    f_start=filtered_idx,
                    f_end=filtered_idx,
                    text=heading,
                )

                blocks.append({
                    "type": "subheading",
                    "text": heading,
                    "meta": meta,
                })

                _inc_count(parsing_state, "subheading")
                filtered_idx += 1
                continue

        # subheading: "* Something :" (star + text + colon) → treat as subheading,
        # and check this BEFORE generic bullet detection.
        if _SUBHEADING_RE.match(ln):
            flush_para("paragraph_default")
            flush_list()
            text = ln.strip()
            # drop the leading "*" but KEEP the trailing ":" so tests can
            # match "Fastest route:" etc.
            text = re.sub(r"^\s*\*\s+", "", text, count=1)
            meta = _make_meta(
                detectors=["subheading_star_colon"],
                f_start=filtered_idx,
                f_end=filtered_idx,
                text=text,
            )
            blocks.append({"type": "subheading", "text": text, "meta": meta})
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
                meta = _make_meta(
                    detectors=["near_miss_banner"],
                    f_start=filtered_idx,
                    f_end=filtered_idx,
                    text=content,
                )
                blocks.append({"type": "subheading", "text": content, "meta": meta})
                _inc_count(parsing_state, "subheading")
                filtered_idx += 1
                continue

        # stand-alone all-caps heading (e.g. "ADDITIONAL NOTES")
        if _UPPER_HEADING_RE.match(ln.strip()):
            flush_para("paragraph_default")
            flush_list()
            text = ln.strip()
            meta = _make_meta(
                detectors=["all_caps_heading"],
                f_start=filtered_idx,
                f_end=filtered_idx,
                text=text,
            )
            blocks.append({"type": "subheading", "text": text, "meta": meta})
            _inc_count(parsing_state, "subheading")
            filtered_idx += 1
            continue

        # Updates: an asterisk-prefixed heading followed immediately
        # by hyphen-prefixed changes introduces a revision group.
        if tag == "updates" and re.match(r"^\s*\*\s+\S", ln):
            next_idx = filtered_idx + 1

            if (
                next_idx < len(lines)
                and re.match(r"^\s*-\s+\S", lines[next_idx] or "")
            ):
                flush_para("paragraph_default")
                flush_list()

                text = re.sub(r"^\s*\*\s+", "", ln, count=1).strip()

                meta = _make_meta(
                    detectors=["subheading_updates_star_dash"],
                    f_start=filtered_idx,
                    f_end=filtered_idx,
                    text=text,
                )

                blocks.append({
                    "type": "subheading",
                    "text": text,
                    "meta": meta,
                })

                _inc_count(parsing_state, "subheading")
                filtered_idx += 1
                continue

        # Scoring: an asterisk-prefixed category followed immediately
        # by at least two label/value pairs introduces a scoring group.
        if (
            tag == "scoring"
            and _BULLET_RE.match(ln)
            and ln.lstrip().startswith("* ")
            and not ln.rstrip().endswith(":")
        ):
            next_idx = filtered_idx + 1

            if next_idx + 1 < len(lines):
                next_line = lines[next_idx] or ""
                following_line = lines[next_idx + 1] or ""

                first_pair = (
                    _PAIR_COLON_RE.match(next_line)
                    or _PAIR_DASH_RE.match(next_line)
                )
                second_pair = (
                    _PAIR_COLON_RE.match(following_line)
                    or _PAIR_DASH_RE.match(following_line)
                )

                if first_pair and second_pair:
                    flush_para("paragraph_default")
                    flush_list()

                    text = re.sub(
                        r"^\s*\*\s+",
                        "",
                        ln,
                        count=1,
                    ).strip()

                    meta = _make_meta(
                        detectors=["subheading_scoring_pairs"],
                        f_start=filtered_idx,
                        f_end=filtered_idx,
                        text=text,
                    )

                    blocks.append({
                        "type": "subheading",
                        "text": text,
                        "meta": meta,
                    })

                    _inc_count(parsing_state, "subheading")
                    filtered_idx += 1
                    continue

        # Overview named topics: a repeated group may put its title
        # and initial description on the same marked source line.
        #
        # Only lines selected by the structural pre-pass qualify.
        # Preserve provenance for both resulting blocks, since they
        # originate from the same physical source line.
        if tag == "overview" and filtered_idx in overview_named_topic_lines:
            match = topic_pattern.match(ln)

            if match:
                title = match.group(1).strip()
                description = match.group(2).strip()

                # Normalise only the first character of the extracted
                # description; sections_raw retains the original text.
                description = description[0].upper() + description[1:]

                flush_para("paragraph_default")
                flush_list()

                heading_meta = _make_meta(
                    detectors=["subheading_overview_named_topic"],
                    f_start=filtered_idx,
                    f_end=filtered_idx,
                    text=title,
                )

                blocks.append({
                    "type": "subheading",
                    "text": title,
                    "meta": heading_meta,
                })

                _inc_count(parsing_state, "subheading")

                paragraph_meta = _make_meta(
                    detectors=["paragraph_overview_named_topic"],
                    f_start=filtered_idx,
                    f_end=filtered_idx,
                    text=description,
                )

                blocks.append({
                    "type": "paragraph",
                    "text": description,
                    "meta": paragraph_meta,
                })

                _inc_count(parsing_state, "paragraph")

                filtered_idx += 1
                continue

        # Overview: GH sometimes uses an asterisk to mark a short
        # heading followed by one or more descriptive source lines.
        #
        # Unlike explicit colon headings, these headings may have no
        # terminal punctuation or may end with a full stop.
        #
        # Require paragraph-style separation and a short title to
        # distinguish this convention from ordinary narrative bullets.
        # Look ahead to the next blank line without consuming the
        # description, allowing normal paragraph classification to
        # preserve the original content and provenance.
        if (
            tag == "overview"
            and ln.lstrip().startswith("* ")
            and _BULLET_RE.match(ln)
        ):
            title = re.sub(
                r"^\s*\*\s+",
                "",
                ln,
                count=1,
            ).strip()

            previous_blank = (
                filtered_idx == 0
                or _BLANK_RE.match(lines[filtered_idx - 1] or "")
            )

            description_lines = []
            next_idx = filtered_idx + 1

            while next_idx < len(lines):
                following = (lines[next_idx] or "").strip()

                if not following:
                    break

                # A new marked or structural entry is not part of
                # the heading's descriptive paragraph.
                if (
                    following.startswith(("*", "-"))
                    or _NUMBERED_RE.match(following)
                    or _ALL_HYPHENS_RE.match(following)
                ):
                    break

                description_lines.append(following)
                next_idx += 1

            description = " ".join(description_lines)

            short_title = (
                len(title) <= 60
                and len(title.split()) <= 9
            )

            has_description = (
                bool(description_lines)
                and len(description_lines[0]) > len(title)
            )

            separated_after = (
                next_idx == len(lines)
                or _BLANK_RE.match(lines[next_idx] or "")
            )

            if (
                previous_blank
                and short_title
                and has_description
                and separated_after
            ):
                flush_para("paragraph_default")
                flush_list()

                meta = _make_meta(
                    detectors=["subheading_overview_description"],
                    f_start=filtered_idx,
                    f_end=filtered_idx,
                    text=title,
                )

                blocks.append({
                    "type": "subheading",
                    "text": title,
                    "meta": meta,
                })

                _inc_count(parsing_state, "subheading")
                filtered_idx += 1
                continue

        # bullets
        if _BULLET_RE.match(ln):
            flush_para("paragraph_default")

            if list_kind not in (None, "bullet_list"):
                flush_list()

            if list_start_idx is None:
                list_start_idx = filtered_idx

            list_kind = "bullet_list"
            item = re.sub(
                r"^\s*[\*\-]\s+",
                "",
                ln,
                count=1,
            ).strip()

            list_acc.append(item)
            list_last_idx = filtered_idx
            filtered_idx += 1
            continue

        # numbered
        if _NUMBERED_RE.match(ln):
            flush_para("paragraph_default")

            if list_kind not in (None, "numbered_list"):
                flush_list()

            if list_start_idx is None:
                list_start_idx = filtered_idx

            list_kind = "numbered_list"
            item = re.sub(
                r"^\s*(?:\d+[\)\].]|[\[\(]\d+[\]\)])\s+",
                "",
                ln,
                count=1,
            ).strip()

            list_acc.append(item)
            list_last_idx = filtered_idx
            filtered_idx += 1
            continue

        # pairs: only in normal mode (not per-line), and NOT in "tips and tricks"
        if not per_line and tag != "tips and tricks":
            m_pair = _PAIR_COLON_RE.match(ln) or _PAIR_DASH_RE.match(ln)
            if m_pair:
                flush_para("paragraph_default")
                flush_list()
                label = m_pair.group(1).strip()
                value = m_pair.group(2).strip()
                text = f"{label}: {value}"
                meta = _make_meta(
                    detectors=["pair_colon" if ":" in ln else "pair_dash"],
                    f_start=filtered_idx,
                    f_end=filtered_idx,
                    text=text,
                )
                blocks.append({
                    "type": "pair",
                    "label": label,
                    "value": value,
                    "meta": meta,
                })
                _inc_count(parsing_state, "pair")
                filtered_idx += 1
                continue

        # GH Scoring sections can contain an uninterrupted list whose
        # individual items have additional unmarked explanations.
        #
        # Unlike a hard wrap, the marked item may already end with
        # complete sentence punctuation. Preserve the explanation
        # separately within the item using a newline.
        #
        # Requiring another marked item immediately afterwards avoids
        # changing ordinary bullet-plus-paragraph endings. Restrict
        # this initial rule to Scoring until other sections have been
        # assessed for headings and nested structures.
        if (
            tag == "scoring"
            and list_kind == "bullet_list"
            and list_acc
            and list_last_idx == filtered_idx - 1
            and filtered_idx + 1 < len(lines)
            and _BULLET_RE.match(lines[filtered_idx + 1] or "")
            and not _is_structural_line(ln)
            and not ln.strip().endswith(":")
        ):
            list_acc[-1] = (
                f"{list_acc[-1]}\n{ln.strip()}"
            )

            list_last_idx = filtered_idx
            filtered_idx += 1
            continue

        # GH sometimes contains hard-wrapped bullet text copied from
        # documents with fixed line widths.
        #
        # Join an unmarked line to the preceding bullet only when:
        # - It immediately follows the preceding list line.
        # - The preceding item lacks sentence-ending punctuation.
        # - The continuation begins with a lowercase character.
        #
        # This conservative rule avoids absorbing ordinary paragraphs,
        # explicit subheadings and separately marked list entries.
        # Ambiguous cases remain separate for subsequent review.
        if (
            list_kind == "bullet_list"
            and list_acc
            and list_last_idx == filtered_idx - 1
        ):
            previous_item = list_acc[-1].rstrip()
            continuation = ln.strip()

            if (
                previous_item
                and continuation
                and not previous_item.endswith((".", "!", "?", ":"))
                and continuation[0].islower()
            ):
                list_acc[-1] = (
                    f"{previous_item} {continuation}"
                )

                list_last_idx = filtered_idx
                filtered_idx += 1
                continue

        # Additional prose within a recognised Tips and Tricks topic
        # belongs after its initial description as separate paragraphs.
        #
        # Apply this only to structurally recognised topic groups.
        # Other Tips and Tricks content retains its existing policy.
        if (
            tag == "tips and tricks"
            and filtered_idx in tips_named_topic_description_lines
        ):
            flush_para("paragraph_default")
            flush_list()

            text = ln.strip()

            if text:
                meta = _make_meta(
                    detectors=["paragraph_tips_topic_continuation"],
                    f_start=filtered_idx,
                    f_end=filtered_idx,
                    text=text,
                )

                blocks.append({
                    "type": "paragraph",
                    "text": text,
                    "meta": meta,
                })

                _inc_count(parsing_state, "paragraph")

            filtered_idx += 1
            continue

        # narrative text
        if per_line:
            flush_list()
            text = ln.strip()
            if text:
                meta = _make_meta(
                    detectors=["paragraph_per_line"],
                    f_start=filtered_idx,
                    f_end=filtered_idx,
                    text=text,
                )
                blocks.append({
                    "type": "paragraph",
                    "text": text,
                    "meta": meta,
                })
                _inc_count(parsing_state, "paragraph")
            filtered_idx += 1
        else:
            # Close any preceding list before accumulating paragraph text.
            # This preserves source order and accurate list provenance.
            flush_list()

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

# --- Fine-tuning helpers: colon preamble binding and hard-wrap flagging ---

def promote_preamble_paragraphs_to_bullet_lists(blocks: list[dict]) -> list[dict]:
    """
    Look for patterns like:

        paragraph: "Known re-releases:"
        paragraph: "\"Street Fighter II - The World Warrior [B-Board 90629B-2]\""
        paragraph: "\"Street Fighter II - The World Warrior [B-Board 90629B-3]\""

    where:
      * the preamble paragraph text ends with ':'
      * the immediately following blocks are also paragraphs
      * those following paragraphs are on consecutive filtered lines

    and convert the *run* of following paragraphs into a single `bullet_list` block.

    The preamble paragraph remains as-is; the list is inserted immediately after it.
    This is deliberately conservative so we don't reclassify unrelated paragraphs.
    """
    if not isinstance(blocks, list) or not blocks:
        return blocks

    out: list[dict] = []
    i = 0
    n = len(blocks)

    while i < n:
        b = blocks[i]
        if isinstance(b, dict) and b.get("type") == "paragraph":
            text = (b.get("text") or "").rstrip()
            meta = b.get("meta") or {}

            # Only treat as a preamble if it ends with ':'.
            if text.endswith(":"):
                items: list[str] = []
                first_item_meta: dict | None = None
                last_item_meta: dict | None = None

                # We will only attach paragraphs that are:
                #  - directly following in the block list, and
                #  - on consecutive filtered lines (no blank-line gaps).
                cur_end = meta.get("filtered_line_end")
                j = i + 1

                while j < n:
                    nb = blocks[j]
                    if not (isinstance(nb, dict) and nb.get("type") == "paragraph"):
                        break

                    nm = nb.get("meta") or {}
                    fs = nm.get("filtered_line_start")
                    # Require adjacency in filtered line numbers to avoid
                    # swallowing paragraphs separated by blank lines.
                    if cur_end is not None and fs is not None and fs == (cur_end + 1):
                        items.append(nb.get("text") or "")
                        if first_item_meta is None:
                            first_item_meta = nm
                        last_item_meta = nm
                        cur_end = nm.get("filtered_line_end")
                        j += 1
                    else:
                        break

                # If we found at least one contiguous paragraph item, emit a list.
                if items:
                    out.append(b)  # keep the preamble paragraph itself

                    # Build list meta based on the preamble + item range.
                    new_meta = dict(meta)
                    det = new_meta.setdefault("detectors", [])
                    if isinstance(det, list) and "preamble_promoted_bullets" not in det:
                        det.append("preamble_promoted_bullets")

                    if first_item_meta is not None and last_item_meta is not None:
                        # Use the item range as the effective range of the list.
                        new_meta["filtered_line_start"] = first_item_meta.get("filtered_line_start")
                        new_meta["filtered_line_end"] = last_item_meta.get("filtered_line_end")
                        new_meta["raw_line_start"] = first_item_meta.get("raw_line_start")
                        new_meta["raw_line_end"] = last_item_meta.get("raw_line_end")

                    new_meta["text_hash"] = _short_hash("\n".join(items))

                    out.append({
                        "type": "bullet_list",
                        "items": items,
                        "meta": new_meta,
                    })

                    # Skip over the paragraphs we just consumed into the list.
                    i = j
                    continue

        # Default: just copy the block through unchanged.
        out.append(b)
        i += 1

    return out

def attach_list_preambles(blocks: list[dict]) -> list[dict]:
    """
    Annotate any paragraph that ends with ':' when the next non-empty block is a list.
    We annotate BOTH:
      - the paragraph (as the 'preamble'), and
      - the following list block (so tests/parsers can read it directly on the list).
    Paragraph meta:
      - preamble_for_list = True
      - preamble_target_index = <index of the next list block>
      - linked_as_preamble_to = <index of the next list block>   # test expects this
      - preamble_text = <paragraph text including ':'>
    List meta:
      - preamble_from_index = <index of the paragraph>
      - preamble_text = <same text>
    """
    if not blocks:
        return blocks

    LIST_TYPES = {"bullet_list", "numbered_list"}

    i = 0
    n = len(blocks)
    while i < n:
        b = blocks[i]
        if b and b.get("type") == "paragraph":
            text = (b.get("text") or "").rstrip()
            if text.endswith(":"):
                # find next non-empty block
                j = i + 1
                while j < n and not blocks[j]:
                    j += 1
                if j < n and blocks[j] and blocks[j].get("type") in LIST_TYPES:
                    # annotate paragraph
                    pmeta = b.setdefault("meta", {})
                    pmeta["preamble_for_list"] = True
                    pmeta["preamble_target_index"] = j
                    pmeta["linked_as_preamble_to"] = j   # <- additional alias to satisfy test
                    pmeta["preamble_text"] = text
                    # annotate target list
                    lmeta = blocks[j].setdefault("meta", {})
                    lmeta["preamble_from_index"] = i
                    lmeta["preamble_text"] = text
        i += 1
    return blocks

def flag_suspect_hard_wraps(blocks: list[dict]) -> list[dict]:
    """
    Flag likely manual hard-wraps between consecutive paragraph blocks.
    Rule: if paragraph i is immediately followed by paragraph i+1 and
    next.filtered_line_start == cur.filtered_line_end + 1,
    mark BOTH paragraphs with meta.suspect_hard_wrap = True and add a
    'suspect_hard_wrap' detector to each.
    (Your writer/sanitiser can strip the top-level flag before JSON output.)
    """
    if not isinstance(blocks, list) or not blocks:
        return blocks

    def _get_filt(meta: dict, key: str) -> int | None:
        try:
            v = meta.get(key)
            return int(v) if v is not None else None
        except Exception:
            return None

    n = len(blocks)
    for i in range(n - 1):
        cur = blocks[i]
        nxt = blocks[i + 1]
        if not (isinstance(cur, dict) and isinstance(nxt, dict)):
            continue
        if cur.get("type") != "paragraph" or nxt.get("type") != "paragraph":
            continue

        cmeta = cur.setdefault("meta", {})
        nmeta = nxt.setdefault("meta", {})

        cur_end = _get_filt(cmeta, "filtered_line_end")
        nxt_start = _get_filt(nmeta, "filtered_line_start")

        if cur_end is not None and nxt_start is not None and (nxt_start == (cur_end + 1)):
            # consecutive paragraphs → flag BOTH
            for m in (cmeta, nmeta):
                m["suspect_hard_wrap"] = True
                det = m.setdefault("detectors", [])
                if isinstance(det, list) and "suspect_hard_wrap" not in det:
                    det.append("suspect_hard_wrap")

    return blocks
