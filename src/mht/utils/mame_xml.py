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
    Interpret a MAME yes/no style attribute as a boolean.
    Falls back to default when missing/empty/unrecognised.
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
    """Return trimmed text of a child element, or default if missing/empty."""
    child = parent.find(tag)
    if child is None or child.text is None:
        return default
    t = child.text.strip()
    return t if t else default
