from __future__ import annotations

"""
Artefact loading for the MHT web preview.

This module loads JSON artefacts from the active release folder, validates basic
shape, and returns a single PreviewData object.
"""

import json
from pathlib import Path
from typing import Any, Dict

from mht.utils.logger import setup_logger
from mht.utils.paths import (
    active_version,
    exotica_wiki_path,
    gh_system_trivia_path,
    mame_machines_path,
    outputs_dir,
    transform_summary_path,
)

from .preview_data import JsonDict, PreviewData

log = setup_logger(__name__)


# ----------------------------------------------------------------------------
# Optional summary path helpers (fallbacks if paths module lacks them)
# ----------------------------------------------------------------------------

try:
    from mht.utils.paths import (  # type: ignore
        history_parsing_summary_path,
        ini_parsing_summary_path,
        mame_parsing_summary_path,
    )
except ImportError:
    def _summaries_dir() -> Path:
        """
        Compute the summaries directory for the active release.

        We expect outputs_dir() to be: data/releases/<ver>/outputs
        So summaries are:           data/releases/<ver>/summaries
        """
        return outputs_dir().parent / "summaries"

    def mame_parsing_summary_path() -> Path:  # type: ignore[misc]
        return _summaries_dir() / "mame_parsing_summary.json"

    def history_parsing_summary_path() -> Path:  # type: ignore[misc]
        return _summaries_dir() / "history_parsing_summary.json"

    def ini_parsing_summary_path() -> Path:  # type: ignore[misc]
        return _summaries_dir() / "ini_parsing_summary.json"


# ----------------------------------------------------------------------------
# JSON loading
# ----------------------------------------------------------------------------

def load_json(path: Path, label: str) -> JsonDict:
    """
    Load a JSON document expected to be a top-level object (dict).

    Raises:
        FileNotFoundError: if the file does not exist.
        RuntimeError: if the JSON cannot be loaded or is not a JSON object.
    """
    if not path.exists():
        raise FileNotFoundError(f"{label} not found at {path.as_posix()}")

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError(f"{label} at {path.as_posix()} is not a JSON object.")

        return data

    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to load {label} from {path.as_posix()}: {exc}") from exc


def find_trivia_path() -> Path:
    """Return the trivia JSON path for the active release."""
    return gh_system_trivia_path()


def normalise_trivia_root(doc: JsonDict) -> JsonDict:
    """
    Trivia JSON may be shaped as:
      { "<machine>": {...}, ... }
    or:
      { "systems": { "<machine>": {...}, ... } }
    or:
      { "games": { "<machine>": {...}, ... } }

    This returns the inner mapping keyed by machine name.
    """
    systems = doc.get("systems")
    if isinstance(systems, dict):
        return systems

    games = doc.get("games")
    if isinstance(games, dict):
        return games

    return doc


def load_preview_data() -> PreviewData:
    """
    Load all JSON artefacts required for the preview server.

    Raises clear exceptions if anything is missing or malformed.
    """
    wiki_path = exotica_wiki_path()
    mame_path = mame_machines_path()
    trivia_path = find_trivia_path()

    mame_sum_path = mame_parsing_summary_path()
    hist_sum_path = history_parsing_summary_path()
    ini_sum_path = ini_parsing_summary_path()
    xform_sum_path = transform_summary_path()

    log.info("Web preview loading artefacts from active release %s", active_version())
    log.info("  wiki:      %s", wiki_path.as_posix())
    log.info("  mame:      %s", mame_path.as_posix())
    log.info("  trivia:    %s", trivia_path.as_posix())
    log.info("  sum(mame): %s", mame_sum_path.as_posix())
    log.info("  sum(hist): %s", hist_sum_path.as_posix())
    log.info("  sum(ini):  %s", ini_sum_path.as_posix())
    log.info("  sum(xfrm): %s", xform_sum_path.as_posix())

    wiki_doc = load_json(wiki_path, "Exotica wiki data")
    wiki_games_obj = wiki_doc.get("games") or {}
    if not isinstance(wiki_games_obj, dict) or not wiki_games_obj:
        raise RuntimeError("Exotica wiki data has no 'games' mapping; run the pipeline first?")

    wiki_games: Dict[str, JsonDict] = {k: v for k, v in wiki_games_obj.items() if isinstance(v, dict)}

    trivia_doc = load_json(trivia_path, "GH system trivia")
    trivia_by_machine = normalise_trivia_root(trivia_doc)

    mame_machines_obj = load_json(mame_path, "MAME machines")
    mame_machines: Dict[str, JsonDict] = {k: v for k, v in mame_machines_obj.items() if isinstance(v, dict)}

    mame_summary = load_json(mame_sum_path, "MAME parsing summary")
    history_summary = load_json(hist_sum_path, "History parsing summary")
    ini_summary = load_json(ini_sum_path, "INI parsing summary")
    transform_summary = load_json(xform_sum_path, "Transform summary")

    machine_order = sorted(wiki_games.keys())

    return PreviewData(
        wiki_doc=wiki_doc,
        wiki_games=wiki_games,
        trivia_by_machine=trivia_by_machine,
        mame_machines=mame_machines,
        mame_summary=mame_summary,
        history_summary=history_summary,
        ini_summary=ini_summary,
        transform_summary=transform_summary,
        machine_order=machine_order,
    )
