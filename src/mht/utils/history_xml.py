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
    Yield (event, element) pairs from `history.xml` using ET.iterparse.

    Parameters
    ----------
    path : Path
        Path to the XML file.
    encoding : str
        Text encoding for the stream.

    Yields
    ------
    tuple[str, xml.etree.ElementTree.Element]
        Event ('start'|'end') and the current element.

    Notes
    -----
    Callers should clear elements (`elem.clear()`) after processing
    to release memory.
    """
    with open(file_path, encoding=encoding) as f:
        yield from ET.iterparse(f, events=("start", "end"))

def capture_history_root_attrs(event: str, elem) -> Optional[Dict[str, str]]:
    """
    Read `<history>` root `version` and `date` attributes, if present.

    Returns
    -------
    (version, date) as (str|None, str|None)
    """
    if event == "start" and getattr(elem, "tag", None) == "history":
        return dict(elem.attrib)
    return None

def get_entry_header(elem: Element, attrs: Iterable[str]) -> Dict[str, Optional[str]]:
    """
    Extract a minimal header tuple from an <entry> element.

    Returns
    -------
    (kind, primary_name, aliases[])
    where kind ∈ {'systems','software',None}
    """
    out: Dict[str, Optional[str]] = {}
    for a in attrs:
        out[a] = elem.attrib.get(a)
    return out

def get_entry_texts(elem: Element, spec: Dict[str, str]) -> Dict[str, str]:
    """
    Return the raw text payload from the <text> child of an <entry>, or "".

    Parameters
    ----------
    entry_el
        <entry> element.

    Returns
    -------
    str
        Raw, unescaped text (may be empty).
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
