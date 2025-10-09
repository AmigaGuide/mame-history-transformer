"""
Filename: utils/titles.py
Author: XtC
"""

from __future__ import annotations
from typing import Dict, List, Tuple, Optional
import re

# Matches ...X(Y)... with no surrounding spaces (used to flag odd bracket usage)
_INFEX_BRACKETS_NO_SPACE_RX = re.compile(r"[A-Za-z0-9]\([^()\[\]]+\)[A-Za-z0-9]")

def collapse_ws(s: str | None) -> str:
    return " ".join((s or "").split())

# ---------- internal helpers (behaviour mirrors transformer.py) ----------

def _clean_token(t: str) -> str:
    t = (t or "").strip()
    while t and t[0] in "-:,/;()[]":
        t = t[1:].lstrip()
    while t and t[-1] in "-:,/;()[]":
        t = t[:-1].rstrip()
    return " ".join(t.split())

def _normalise_inside_group(s: str) -> Tuple[str, bool]:
    changed = False
    out: List[str] = []
    dR = dS = 0
    i = 0
    while i < len(s):
        if dR == 0 and dS == 0:
            if s.startswith(" - ", i):
                out.append(", "); changed = True; i += 3; continue
            if s.startswith(" / ", i):
                out.append(", "); changed = True; i += 3; continue
        ch = s[i]
        if ch == "(": dR += 1
        elif ch == ")": dR = max(0, dR - 1)
        elif ch == "[": dS += 1
        elif ch == "]": dS = max(0, dS - 1)
        out.append(ch); i += 1
    return ("".join(out), changed)

def _top_level_groups(unit: str) -> List[Tuple[int, int, str, str]]:
    groups: List[Tuple[int, int, str, str]] = []
    dR = dS = 0
    i = 0
    while i < len(unit):
        ch = unit[i]
        if ch in "([":
            if dR == 0 and dS == 0:
                start = i
                btype = ch
                i += 1
                dR += (ch == "(")
                dS += (ch == "[")
                while i < len(unit) and (dR > 0 or dS > 0):
                    if unit[i] == "(": dR += 1
                    elif unit[i] == ")": dR -= 1
                    elif unit[i] == "[": dS += 1
                    elif unit[i] == "]": dS -= 1
                    i += 1
                end = i - 1
                raw = unit[start + 1:end]
                content, _ = _normalise_inside_group(raw)
                groups.append((start, end, "(" if btype == "(" else "[", content))
                continue
        i += 1
    return groups

def _first_trailing_start(unit: str, groups: List[Tuple[int, int, str, str]]) -> Optional[int]:
    for (start, end, _, _) in groups:
        if start == 0:
            return start
        if unit[start - 1].isspace():
            return start
    return None

def _split_outside_tokens_after(unit: str, groups: List[Tuple[int, int, str, str]], from_index: int) -> List[str]:
    tokens: List[str] = []
    spans = [(s, e) for (s, e, _, _) in groups if s >= from_index]
    spans.sort()
    cursor = from_index
    for (s, e) in spans:
        if s > cursor:
            frag = unit[cursor:s].strip()
            if frag:
                tokens.append(_clean_token(frag))
        cursor = e + 1
    if cursor < len(unit):
        frag = unit[cursor:].strip()
        if frag:
            tokens.append(_clean_token(frag))
    return [t for t in tokens if t]

def _parse_unit(unit_text: str) -> Tuple[str, str, List[str], List[str], Dict[str, bool]]:
    warn = {"odd_separator_usage": False}
    groups = _top_level_groups(unit_text)
    first_tr_start = _first_trailing_start(unit_text, groups)
    cut = first_tr_start if first_tr_start is not None else len(unit_text)
    head = unit_text[:cut]

    # subtitle split, prefer earliest of " - " or ":"
    sub_pos: Optional[int] = None
    chosen: Optional[str] = None
    for sep in (" - ", ":"):
        idx = head.find(sep)
        if idx != -1 and (sub_pos is None or idx < sub_pos):
            sub_pos = idx
            chosen = sep
    if sub_pos is not None:
        base = head[:sub_pos].strip()
        subtitle = head[sub_pos + len(chosen):].strip()
    else:
        base = head.strip()
        subtitle = ""

    for (_, _, _, content_raw) in groups:
        _, changed = _normalise_inside_group(content_raw)
        if changed:
            warn["odd_separator_usage"] = True
            break

    outside_tokens: List[str] = []
    if first_tr_start is not None:
        outside_tokens = _split_outside_tokens_after(unit_text, groups, from_index=groups[0][1] + 1)

    group_contents = [g[3].strip() for g in groups]
    return base, subtitle, group_contents, outside_tokens, warn

def _split_top_level(text: str, delim: str) -> List[str]:
    out, buf = [], []
    dR = dS = 0
    i, L, dlen = 0, len(text), len(delim)
    while i < L:
        if dR == 0 and dS == 0 and text.startswith(delim, i):
            out.append("".join(buf)); buf = []; i += dlen; continue
        ch = text[i]
        if ch == "(": dR += 1
        elif ch == ")": dR = max(0, dR - 1)
        elif ch == "[": dS += 1
        elif ch == "]": dS = max(0, dS - 1)
        buf.append(ch); i += 1
    out.append("".join(buf))
    return out

# ---------- public API ----------

def find_unbalanced(full: str) -> Tuple[bool, bool]:
    dR = dS = 0
    for ch in full or "":
        if ch == "(": dR += 1
        elif ch == ")": dR -= 1
        elif ch == "[": dS += 1
        elif ch == "]": dS -= 1
    return (dR != 0, dS != 0)

def find_infix_brackets_no_spaces(s: str) -> bool:
    return _INFEX_BRACKETS_NO_SPACE_RX.search(s or "") is not None

def parse_description(full_desc: str) -> Tuple[Dict[str, str], Dict[str, List[Dict[str, str]]]]:
    """
    Parse a MAME description into numbered title/subtitle/version fields.

    Splits multi-part titles (e.g. "Foo / Bar") into title1, title2, ...
    Extracts a single `global_version` when appropriate and surfaces
    anomalies (unbalanced brackets, odd infix groups) for QA.

    Returns
    -------
    (desc_fields, anomalies)
        `desc_fields` is a dict with keys like 'title1', 'subtitle1',
        'version1', ... and 'global_version'.
        `anomalies` maps anomaly type -> list of {'example': <string>}.
    """                
    anomalies: Dict[str, List[Dict[str, str]]] = {
        "unbalanced_round_brackets": [],
        "unbalanced_square_brackets": [],
        "infix_brackets_no_spaces": [],
        "ambiguous_trailing_tokens": [],
        "odd_separator_usage": [],
    }

    unb_round, unb_square = find_unbalanced(full_desc or "")
    if unb_round:  anomalies["unbalanced_round_brackets"].append({"example": full_desc})
    if unb_square: anomalies["unbalanced_square_brackets"].append({"example": full_desc})
    if find_infix_brackets_no_spaces(full_desc or ""):
        anomalies["infix_brackets_no_spaces"].append({"example": full_desc})

    units = _split_top_level(full_desc or "", " / ")

    unit_info = []
    total_top_groups = 0
    for u in units:
        base, sub, group_contents, outside_tokens, warn = _parse_unit(u)
        unit_info.append((base, sub, group_contents, outside_tokens, warn))
        total_top_groups += len(group_contents)
        if warn.get("odd_separator_usage"):
            anomalies["odd_separator_usage"].append({"example": full_desc})
        if outside_tokens:
            anomalies["ambiguous_trailing_tokens"].append({"example": full_desc})

    # Build numbered fields
    desc: Dict[str, str] = {}
    for idx in range(len(unit_info)):
        desc[f"title{idx+1}"] = ""
        desc[f"subtitle{idx+1}"] = ""
        desc[f"version{idx+1}"] = ""
    for idx, (base, sub, _, _, _) in enumerate(unit_info, start=1):
        desc[f"title{idx}"] = base
        desc[f"subtitle{idx}"] = sub

    # Global version logic (exactly as before)
    global_parts: List[str] = []
    if total_top_groups == 1:
        for (_, _, groups, outs, _) in unit_info:
            if groups:
                global_parts.append(groups[0])
                for t in outs:
                    global_parts.append(t)
                break
    else:
        for idx, (_, _, groups, outs, _) in enumerate(unit_info, start=1):
            if groups:
                desc[f"version{idx}"] = groups[0]
                for extra in groups[1:]:
                    global_parts.append(extra)
            for t in outs:
                global_parts.append(t)

    desc["global_version"] = ", ".join(p for p in global_parts if p)
    return desc, anomalies

def unit_count_from_desc(desc_fields: Dict[str, str]) -> int:
    nums = []
    for k in desc_fields.keys():
        if k.startswith("title") and k[5:].isdigit():
            nums.append(int(k[5:]))
    return max(nums) if nums else 1

def wiki_page_name_from_desc(desc_fields: Dict[str, str]) -> str:
    title = (desc_fields.get("title1") or "").strip()
    subtitle = (desc_fields.get("subtitle1") or "").strip()
    return f"{title}: {subtitle}" if subtitle else title

def build_redirect_sources(desc_fields: Dict[str, str], wiki_page_name: str) -> List[str]:
    """
    Deterministically compute redirect source names for a wiki page.

    Excludes the exact target (case-insensitive). Adds titles/subtitles
    for units >= 2 and the bare title for unit 1 when target is title+subtitle.
    """
    sources: List[str] = []
    seen_ci: set[str] = set()

    def add(name: str):
        n = collapse_ws(name)
        if not n:
            return
        if n.casefold() == (wiki_page_name or "").casefold():
            return
        ci = n.casefold()
        if ci not in seen_ci:
            seen_ci.add(ci)
            sources.append(n)

    n_units = unit_count_from_desc(desc_fields)
    # Titles/subtitles for units 2..N
    for i in range(2, n_units + 1):
        ti = (desc_fields.get(f"title{i}") or "").strip()
        si = (desc_fields.get(f"subtitle{i}") or "").strip()
        if ti:
            add(ti)
            if si:
                add(f"{ti}: {si}")

    # For unit 1, add bare title if title+subtitle is the target
    t1 = (desc_fields.get("title1") or "").strip()
    s1 = (desc_fields.get("subtitle1") or "").strip()
    if t1 and s1:
        add(t1)

    return sources
