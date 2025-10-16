from __future__ import annotations
from typing import Tuple, Dict, Any

from mht.utils.io import read_json
from mht.utils.paths import (
    mame_machines_path,
    parent_index_path,
    gh_system_ports_path,
    ini_classifications_path,
    exotica_wiki_path,
    exotica_raw_path,
    exotica_pages_path,
    title_overrides_path,
)


def _path_s(p) -> str:
    """Normalise a Path to a forward-slash string for summaries."""
    return str(p).replace("\\", "/")

def load_stage_inputs() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    Load all inputs required by the transform stage from the active release.
    Returns (mame_machines, parent_index, gh_system_ports, ini_classifications)
    """
    mame_machines       = read_json(mame_machines_path()) or {}
    parent_idx          = read_json(parent_index_path()) or {}
    gh_ports            = read_json(gh_system_ports_path()) or {}
    ini_classifications = read_json(ini_classifications_path()) or {}
    return mame_machines, parent_idx, gh_ports, ini_classifications

def build_inputs_map(*, have_overrides: bool) -> Dict[str, str]:
    """
    Assemble the 'inputs' block for the transform summary (per-release paths).
    """
    inputs = {
        "mame_machines":       _path_s(mame_machines_path()),
        "ini_classifications": _path_s(ini_classifications_path()),
        "mame_parent_index":   _path_s(parent_index_path()),
        "gh_system_ports":     _path_s(gh_system_ports_path()),
    }
    ov = title_overrides_path()
    if have_overrides and ov.exists():
        inputs["title_overrides"] = _path_s(ov)
    return inputs

def build_outputs_map() -> Dict[str, str]:
    """
    Assemble the 'outputs' block for the transform summary (per-release paths).
    """    
    return {
        "exotica_lit_wiki":         _path_s(exotica_wiki_path()),
        "exotica_lit_raw_data":     _path_s(exotica_raw_path()),
        "wiki_pages_and_redirects": _path_s(exotica_pages_path()),
    }
    