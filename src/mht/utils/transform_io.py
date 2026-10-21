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


def _load_required_json(path) -> Dict[str, Any]:
    """
    Load a required transform input.

    An empty dictionary is valid, but a missing, unreadable
    or incorrectly structured JSON document is not.
    """
    data = read_json(path)

    if data is None:
        raise ValueError(
            f"Required transform input could not be loaded: {path}"
        )

    if not isinstance(data, dict):
        raise ValueError(
            f"Required transform input is not a JSON object: {path}"
        )

    return data


def load_stage_inputs() -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
]:
    """
    Load and validate all required transform inputs.

    Returns:
        (mame_machines, parent_index,
         gh_system_ports, ini_classifications)

    Raises ValueError if a required input cannot be loaded
    or does not contain a JSON object.
    """
    mame_machines = _load_required_json(mame_machines_path())
    parent_idx = _load_required_json(parent_index_path())
    gh_ports = _load_required_json(gh_system_ports_path())
    ini_classifications = _load_required_json(
        ini_classifications_path()
    )

    return (
        mame_machines,
        parent_idx,
        gh_ports,
        ini_classifications,
    )


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

def _xml_input_from_cache(cache: dict[str, Any], leaf: str, kind: str) -> dict[str, Any]:
    rec = cache.get(leaf) or {}
    return {
        "kind": kind,                        # e.g. 'history_xml'
        "leaf": leaf,                        # expected: 'history.xml'
        "encoding": rec.get("encoding") or "utf-8",
        "detected_via": rec.get("detected_via"),
        "zip_archive": rec.get("zip_archive"),
        "zip_member": rec.get("zip_member"),
        "zip_crc32": rec.get("zip_crc32"),
        "zip_size_bytes": rec.get("zip_size_bytes"),
        "xml_decl_encoding": rec.get("xml_decl_encoding"),
        "xml_bom": rec.get("xml_bom"),
        "version_hint": rec.get("xml_root_attrs") or {},   # {'version': '2.80', ...}
    }
