from __future__ import annotations

from typing import Tuple, Dict, Any

from mht.utils.io import read_json
from mht.utils.paths import (
    MAME_MACHINES_PATH,
    PARENT_INDEX_PATH,
    GH_SYSTEM_PORTS_PATH,
    INI_CLASS_PATH,
    EXOTICA_WIKI,
    EXOTICA_RAW,
    EXOTICA_PAGES,
)


def _path_s(p) -> str:
    """Normalise a Path to a forward-slash string for summaries."""
    return str(p).replace("\\", "/")

def load_stage_inputs() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    Load all inputs required by the transform stage using the single-source paths.

    Returns
    -------
    (mame_machines, parent_index, gh_system_ports, ini_classifications)
    """
    mame_machines       = read_json(MAME_MACHINES_PATH) or {}
    parent_index        = read_json(PARENT_INDEX_PATH) or {}
    gh_system_ports     = read_json(GH_SYSTEM_PORTS_PATH) or {}
    ini_classifications = read_json(INI_CLASS_PATH) or {}
    return mame_machines, parent_index, gh_system_ports, ini_classifications

def build_inputs_map(*, have_overrides: bool, overrides_path) -> Dict[str, str]:
    """
    Assemble the 'inputs' block for the transform summary in one place.
    """
    inputs = {
        "mame_machines":       _path_s(MAME_MACHINES_PATH),
        "ini_classifications": _path_s(INI_CLASS_PATH),
        "mame_parent_index":   _path_s(PARENT_INDEX_PATH),
        "gh_system_ports":     _path_s(GH_SYSTEM_PORTS_PATH),
    }
    if have_overrides and overrides_path:
        inputs["title_overrides"] = _path_s(overrides_path)
    return inputs

def build_outputs_map() -> Dict[str, str]:
    """
    Assemble the 'outputs' block for the transform summary in one place.
    """
    return {
        "exotica_lit_wiki":         _path_s(EXOTICA_WIKI),
        "exotica_lit_raw_data":     _path_s(EXOTICA_RAW),
        "wiki_pages_and_redirects": _path_s(EXOTICA_PAGES),
    }
