"""
History XML iteration helpers.
"""

from __future__ import annotations
from typing import Iterator, Tuple, Optional, Dict, Iterable
from xml.etree import ElementTree as ET
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
