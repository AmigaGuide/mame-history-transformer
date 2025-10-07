from __future__ import annotations
from typing import Dict, Any, List
from mht.utils.titles import collapse_ws, parse_description
from mht.utils.mame_titles import _raw_mame_title

def dedupe_ci_preserve_order(items: List[str] | None) -> List[str]:
    """Case-insensitive dedupe while keeping first-seen order."""
    out: List[str] = []
    seen: set[str] = set()
    for s in items or []:
        key = (s or "").casefold()
        if key and key not in seen:
            seen.add(key)
            out.append(s)
    return out

def _primary_redirects_for_unit1(desc_fields: Dict[str, str], target_page_name: str) -> List[str]:
    """Build “primary” redirects just from unit1 forms (Title, Title: Subtitle)."""
    t = collapse_ws((desc_fields.get("title1") or "").strip())
    s = collapse_ws((desc_fields.get("subtitle1") or "").strip())
    target_ci = (target_page_name or "").casefold()
    out: List[str] = []
    if not t:
        return out
    if s:
        full = collapse_ws(f"{t}: {s}")
        if full.casefold() != target_ci:
            out.append(full)
        if t.casefold() != target_ci:
            out.append(t)
    else:
        if t.casefold() != target_ci:
            out.append(t)
    return dedupe_ci_preserve_order(out)

def clone_primary_redirects(clone_machine: str,
                            mame: Dict[str, Any],
                            target_page_name: str) -> List[str]:
    """
    For a clone machine, parse its raw MAME title and return its unit-1 redirects
    (Title / Title: Subtitle), excluding the exact target page name.
    """
    minfo = mame.get(clone_machine) or {}
    raw = _raw_mame_title(minfo, clone_machine)
    desc_fields, _ = parse_description(raw)
    return _primary_redirects_for_unit1(desc_fields, target_page_name)
