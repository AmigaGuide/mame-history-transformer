"""
XML accessors and small normalisers for MAME XML parsing.

Notable helpers:
- element_text(), attr_text(), attr_yesno_bool(): safe element/attribute readers.
- int_or_none(): strict integer parser for numeric attributes (digits only).
"""

from __future__ import annotations

from typing import Any, Optional, Tuple, Dict, Iterator
from xml.etree import ElementTree as ET
from pathlib import Path

from mht.utils.booleans import yesno_str


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

def capture_root_attrs(event: str, elem) -> Tuple[str | None, str | None]:
    """
    When iterparse hits the <mame> start, extract ('build', 'mameconfig'), else (None, None).
    """
    if event == "start" and getattr(elem, "tag", None) == "mame":
        return elem.attrib.get("build"), elem.attrib.get("mameconfig")
    return None, None

def get_machine_header(elem) -> Dict[str, str | None]:
    """
    Extract core header attributes from a <machine> element.

    Returns a dict with the same keys the parser used to set:
      - cloneof: Optional[str]
      - isbios:  "yes"/"no"
      - isdevice:"yes"/"no"
      - ismechanical:"yes"/"no"
      - sampleof: Optional[str]
      - sourcefile: Optional[str]
      - romof: Optional[str]  # legacy; may be empty in modern MAME
    """
    cloneof      = attr_text(elem, "cloneof")
    isbios       = yesno_str(attr_yesno_bool(elem, "isbios"))
    isdevice     = yesno_str(attr_yesno_bool(elem, "isdevice"))
    ismechanical = yesno_str(attr_yesno_bool(elem, "ismechanical"))
    sampleof     = attr_text(elem, "sampleof")
    sourcefile   = attr_text(elem, "sourcefile")
    romof        = attr_text(elem, "romof")  # retained for completeness

    return {
        "cloneof": cloneof,
        "isbios": isbios,
        "isdevice": isdevice,
        "ismechanical": ismechanical,
        "sampleof": sampleof,
        "sourcefile": sourcefile,
        "romof": romof,
    }

def get_core_text_fields(elem) -> Tuple[Optional[str], str, str]:
    """
    Return (description, year_raw, manufacturer_raw) from a <machine> element.

    Behaviour matches the existing parser:
    - description: normalised text or None when missing/blank
    - year_raw: normalised text, '' when missing
    - manufacturer_raw: normalised text, '' when missing
    """
    description = element_text(elem, "description", default=None) or None
    year_raw = element_text(elem, "year", default="")
    manufacturer_raw = element_text(elem, "manufacturer", default="")
    return description, year_raw, manufacturer_raw

def iter_mame_events(file_path: Path, encoding: str) -> Iterator[Tuple[str, ET.Element]]:
    """
    Stream (event, elem) pairs from a MAME XML file using ElementTree.iterparse.

    - Opens the file with the provided encoding.
    - Yields both 'start' and 'end' events.
    - Caller is responsible for calling elem.clear() after handling an 'end' event
      for large elements (e.g., <machine>) to keep memory usage low.

    Usage pattern (typical):
        for event, elem in iter_mame_events(path, enc):
            # capture root attrs on 'start' 'mame'
            # process 'end' 'machine' blocks, then elem.clear()
    """
    with open(file_path, encoding=encoding) as f:
        yield from ET.iterparse(f, events=("start", "end"))
