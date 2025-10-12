"""
History XML helpers: event streaming and small accessors.

Includes:
- iter_history_events(): yields ('start'|'end', Element) pairs for history.xml.
- capture_history_root_attrs(): returns <history> root attributes on the 'start' event.
- classify_entry(): classifies an <entry> as 'systems'/'software' and extracts names.
- get_entry_header(): picks specific attributes from an <entry>.
- get_entry_texts(): reads specific child text nodes from an <entry>.
"""

from __future__ import annotations
from typing import Iterator, Tuple, Optional, Dict, Iterable, List
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import Element  # for type hints
from pathlib import Path

from mht.utils.mame_xml import element_text


def iter_history_events(file_path: Path, encoding: str) -> Iterator[Tuple[str, ET.Element]]:
    """
    Stream (event, elem) pairs from a Gaming-History XML using ElementTree.iterparse.

    - Opens the file with the provided encoding.
    - Yields both 'start' and 'end' events.
    - Caller should call elem.clear() after handling large 'end' elements to keep memory usage low.
    """
    with open(file_path, encoding=encoding) as f:
        yield from ET.iterparse(f, events=("start", "end"))

def capture_history_root_attrs(event: str, elem) -> Optional[Dict[str, str]]:
    """
    If this is the start of the <history> root element, return its attributes as a dict.
    Otherwise return None. Leaves interpretation of fields to the caller.
    """
    if event == "start" and getattr(elem, "tag", None) == "history":
        return dict(elem.attrib)
    return None

def get_entry_header(elem: Element, attrs: Iterable[str]) -> Dict[str, Optional[str]]:
    """
    Extract a small set of attributes from a history <entry>/<game> element.

    Example: get_entry_header(elem, attrs=("name", "source"))
    Returns { "name": "...", "source": "..." } with missing ones as None.
    """
    out: Dict[str, Optional[str]] = {}
    for a in attrs:
        out[a] = elem.attrib.get(a)
    return out

def get_entry_texts(elem: Element, spec: Dict[str, str]) -> Dict[str, str]:
    """
    Extract specific child text nodes from a history entry element.

    spec maps tag -> default, e.g. { "description": "", "year": "", "publisher": "" }.
    Returns a dict with the same keys, using element_text() for normalised reads.
    """
    out: Dict[str, str] = {}
    for tag, default in spec.items():
        out[tag] = element_text(elem, tag, default=default)
    return out

def classify_entry(elem: Element) -> Tuple[str, Optional[str], List[str]]:
    """
    Classify a history <entry> element and return:
      - kind: "systems", "software", or "unknown"
      - primary: primary system name (first <system name="...">) or None
      - aliases: remaining system names (possibly empty)

    Behaviour mirrors the inline logic previously in history_parser:
    - If <systems> exists, we read its <system name="..."> children.
      * If there are names, primary = names[0], aliases = names[1:].
      * If there are no names, kind stays "systems" with primary=None (caller should skip).
    - If <software> exists (and <systems> does not), kind is "software".
    - Otherwise "unknown".
    """
    systems_elem = elem.find("systems")
    if systems_elem is not None:
        names = [s.attrib.get("name") for s in systems_elem.findall("system") if s.attrib.get("name")]
        if names:
            return "systems", names[0], names[1:]
        return "systems", None, []  # no names → caller should skip

    if elem.find("software") is not None:
        return "software", None, []

    return "unknown", None, []
