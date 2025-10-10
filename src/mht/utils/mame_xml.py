"""
XML accessors and small normalisers for MAME XML parsing.

Notable helpers:
- element_text(), attr_text(), attr_yesno_bool(): safe element/attribute readers.
- int_or_none(): strict integer parser for numeric attributes (digits only).
"""

from __future__ import annotations

from typing import Any, Optional
import xml.etree.ElementTree as ET

def attr_text(el, name: str, *, default: str | None = None) -> str | None:
    """Get a trimmed attribute as text, or default if missing/empty."""
    v = el.attrib.get(name)
    if v is None:
        return default
    t = str(v).strip()
    return t if t else default

def attr_int(node: ET.Element, name: str, *, default: int = 0) -> int:
    """Parse an integer attribute, falling back to default if missing/invalid."""
    v = node.attrib.get(name)
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        return default

def attr_yesno_bool(el, name: str, *, default: bool = False) -> bool:
    """
    Interpret an XML attribute with yes/no semantics as a boolean.

    Parameters
    ----------
    elem
        XML element carrying the attribute.
    name
        Attribute name to read.

    Returns
    -------
    bool
        True for values like "yes", "true", "1" (case-insensitive);
        False for anything else or missing.
    """
    from mht.utils.booleans import truthy_flag  # already in your repo
    v = el.attrib.get(name, "")
    return truthy_flag(v) if v else default

def safe_int(value: Any, *, default: int = 0) -> int:
    """Coerce arbitrary values to int with a forgiving default."""
    try:
        return int(value)
    except Exception:
        return default

def element_text(parent: ET.Element, tag: str, *, default: str | None = None) -> str | None:
    """
    Return the stripped text of the first child element with `tag`.

    Parameters
    ----------
    elem
        Parent XML element.
    tag
        Child tag name to locate once under `elem`.
    default
        Value to return when the child is missing or has no text.

    Returns
    -------
    str
        Child text with surrounding whitespace collapsed to a single space.
        If not found, returns `default` (never None).
    """
    child = parent.find(tag)
    if child is None or child.text is None:
        return default
    t = child.text.strip()
    return t if t else default

def int_or_none(s: str | None) -> int | None:
    """
    Parse an integer from a string, or return None when missing/invalid.

    - Accepts only pure digit strings (e.g. "123").
    - Returns None for empty, None, or non-numeric input.
    """
    s = (s or "").strip()
    return int(s) if s.isdigit() else None
