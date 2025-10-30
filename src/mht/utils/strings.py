from __future__ import annotations

from typing import List

from mht.utils.media import join_with_ampersand  # reuse existing one

_SPLIT_TOKEN = "/"  # we split on "/" outside any parentheses


def split_outside_parens(text: str | None) -> List[str]:
    """
    Split `text` on '/' that are NOT inside parentheses, preserving everything else.
    Returns trimmed parts; empty parts are dropped.
    """
    s = text or ""
    parts, buf, depth = [], [], 0
    for ch in s:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == _SPLIT_TOKEN and depth == 0:
            frag = "".join(buf).strip()
            if frag:
                parts.append(frag)
            buf = []
        else:
            buf.append(ch)
    last = "".join(buf).strip()
    if last:
        parts.append(last)
    return parts

def format_manufacturers_for_wiki(raw: str | None) -> str:
    """
    Split on '/' outside parentheses and rejoin with ' & ' (Oxford-comma style for >2).
    Examples:
      'ADK / SNK'           -> 'ADK & SNK'
      'Capcom (CPS-2) / CPS'-> 'Capcom (CPS-2) & CPS'
    """
    parts = [p for p in split_outside_parens(raw) if p]
    if not parts:
        return ""
    return join_with_ampersand(parts)

def year_bucket_key(year_text: str | None) -> str:
    """
    Return a summary bucket key for the <year> string: 'YYYY' when 4 digits, else 'unknown'.
    """
    s = (year_text or "").strip()
    return s if len(s) == 4 and s.isdigit() else "unknown"

def manufacturer_bucket_key(text: str | None) -> str:
    """
    Return a summary bucket key for <manufacturer>: cleaned string or 'unknown' if effectively empty.
    Mirrors the parser's punctuation-trim behaviour.
    """
    s = (text or "").strip()
    if not s:
        return "unknown"
    cleaned = s.strip("-.,;:/()[]{}").strip()
    return cleaned if cleaned else "unknown"

def digits_score(s: str) -> int:
    """
    Count how many digit characters appear in the input.
    Used by provenance heuristics when ranking candidate names/paths.
    """
    if not s:
        return 0
    return sum(ch.isdigit() for ch in s)
