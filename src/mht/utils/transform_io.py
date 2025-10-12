from __future__ import annotations

from typing import Tuple, Dict, Any

from mht.utils.io import read_json
from mht.utils.paths import (
    MAME_MACHINES_PATH,
    PARENT_INDEX_PATH,
    GH_SYSTEM_PORTS_PATH,
    INI_CLASS_PATH,
)


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
