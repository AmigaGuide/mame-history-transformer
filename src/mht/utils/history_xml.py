"""
History XML iteration helpers.
"""

from __future__ import annotations
from typing import Iterator, Tuple
from xml.etree import ElementTree as ET
from pathlib import Path

def iter_history_events(file_path: Path, encoding: str) -> Iterator[Tuple[str, ET.Element]]:
    """
    Stream (event, elem) pairs from a Gaming-History XML using ElementTree.iterparse.

    - Opens the file with the provided encoding.
    - Yields both 'start' and 'end' events.
    - Caller should call elem.clear() after handling large 'end' elements to keep memory usage low.
    """
    with open(file_path, encoding=encoding) as f:
        yield from ET.iterparse(f, events=("start", "end"))
