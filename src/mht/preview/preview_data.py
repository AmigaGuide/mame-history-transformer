from __future__ import annotations

"""
Data structures used by the MHT web preview.

Kept in a dedicated module so other preview modules can share types without
creating circular imports.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class PreviewData:
    """
    In-memory snapshot of all artefacts required by the preview server.
    """
    wiki_doc: JsonDict
    wiki_games: Dict[str, JsonDict]
    trivia_by_machine: JsonDict
    mame_machines: Dict[str, JsonDict]

    # Summaries
    mame_summary: JsonDict
    history_summary: JsonDict
    ini_summary: JsonDict
    transform_summary: JsonDict

    # Stable navigation order for /game/<machine>
    machine_order: List[str]

    # Optional audit evidence, loaded once when opening the Preview.
    history_audit: JsonDict = field(default_factory=dict)
