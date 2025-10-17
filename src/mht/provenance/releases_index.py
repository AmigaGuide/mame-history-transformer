from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

from mht.utils.io import write_json
from mht.utils.paths import (
    DATA_DIR,
    release_root,
    archives_dir,
    extracted_dir,
    outputs_dir,
    summaries_dir,
    stamps_dir,
    mame_xml_path,
    history_xml_path,
    ini_game_path,
    ini_category_path,
    ini_type_path,
    mame_machines_path,
    parent_index_path,
    gh_system_ports_path,
    ini_classifications_path,
    exotica_raw_path,
    exotica_wiki_path,
    exotica_pages_path,
    mame_summary_path,
    history_summary_path,
    ini_summary_path,
)

# ---------- small helpers ----------

def _utc_now_iso() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

def _safe_load_json(p: Path) -> Any | None:
    try:
        if p.exists() and p.is_file():
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return None
    return None

def _file_meta(p: Path) -> Dict[str, Any] | None:
    try:
        st = p.stat()
        return {
            "path": p.as_posix(),
            "size_bytes": st.st_size,
            "modified_utc": datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z",
        }
    except FileNotFoundError:
        return None

def _numcore_and_suffix(raw: str | None) -> Tuple[Tuple[int, ...], Optional[str]]:
    """
    Extract dotted numeric core as a tuple plus optional suffix.
    Accepts values like '0.280', '0.280-rc1', '2.79a', etc.
    """
    if not raw:
        return ((), None)
    s = raw.strip()
    # split into alnum runs separated by punctuation; first run of numbers with dots is the core
    # pragmatic approach:
    core = []
    token = ""
    for ch in s:
        if ch.isdigit() or ch == ".":
            token += ch
        else:
            if token:
                core = token.split(".")
                break
    if not core and token:
        core = token.split(".")
    try:
        core_tuple = tuple(int(x) for x in core if x != "")
    except ValueError:
        core_tuple = ()
    # suffix = raw with leading core removed (best-effort)
    suffix = None
    if core_tuple:
        core_str = ".".join(str(n) for n in core_tuple)
        idx = s.find(core_str)
        if idx >= 0:
            rest = s[idx + len(core_str):].lstrip(" -_.")
            suffix = rest or None
    return (core_tuple, suffix)

def _same_numeric_core(*raws: Optional[str]) -> bool:
    cores = []
    for r in raws:
        core, _ = _numcore_and_suffix(r)
        if not core:
            return False
        cores.append(core)
    return len(set(cores)) == 1

def _read_versions_from_summaries(ver: str) -> Dict[str, Any]:
    """
    Pull concise version info from the small summary JSONs only.
    """
    ms = _safe_load_json(mame_summary_path(ver)) or {}
    hs = _safe_load_json(history_summary_path(ver)) or {}
    ins = _safe_load_json(ini_summary_path(ver)) or {}

    # canonical header-first paths, with fallbacks for older shapes
    def _get(d, *path, default=None):
        cur = d
        for k in path:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    mame_build   = _get(ms, "header", "versions", "mame_build") or _get(ms, "mame", "build")
    mame_xml_ver = _get(ms, "header", "versions", "mame_xml_version")

    hist_ver  = _get(hs, "header", "versions", "gh_version") or _get(hs, "history", "version")
    hist_date = _get(hs, "header", "versions", "gh_date")    or _get(hs, "history", "date")

    # INI versions as a mapping (filename -> version string)
    ini_versions: Dict[str, str] = {}
    # new shape
    files_node = _get(ins, "ini", "files")
    if isinstance(files_node, dict):
        for item in files_node.values():
            fn = (item.get("filename") or item.get("path") or "").strip()
            v  = item.get("version") or {}
            ver = v.get("mame_version") or v.get("raw") or "Unknown"
            if fn:
                ini_versions[fn] = ver
    # legacy shapes
    if not ini_versions:
        files_list = ins.get("files")
        if isinstance(files_list, list):
            for item in files_list:
                fn = (item.get("filename") or item.get("path") or "").strip()
                v  = item.get("version") or {}
                ver = v.get("mame_version") or v.get("raw") or "Unknown"
                if fn:
                    ini_versions[fn] = ver
    if not ini_versions:
        for item in (ins.get("inputs") or ins.get("ini", {}).get("inputs") or []):
            fn = (item.get("filename") or item.get("path") or "").strip()
            v  = item.get("version") or {}
            ver = v.get("mame_version") or v.get("raw") or "Unknown"
            if fn:
                ini_versions[fn] = ver

    return {
        "mame_build": mame_build,
        "mame_xml_version": mame_xml_ver,
        "history_version": hist_ver,
        "history_date": hist_date,
        "ini_versions": ini_versions,
    }

# ---------- main builder ----------

def _summaries_meta(ver: str) -> Dict[str, Any]:
    return {
        "mame_parsing_summary": _file_meta(mame_summary_path(ver)),
        "history_parsing_summary": _file_meta(history_summary_path(ver)),
        "ini_parsing_summary": _file_meta(ini_summary_path(ver)),
        "transform_summary": _file_meta(summaries_dir(ver) / "transform_summary.json"),
        "run_manifest": _file_meta(summaries_dir(ver) / "run_manifest.json"),
    }

def _stamps_meta(ver: str) -> Dict[str, Any]:
    sd = stamps_dir(ver)
    return {
        "mame": _file_meta(sd / "mame.json"),
        "history": _file_meta(sd / "history.json"),
        "ini": _file_meta(sd / "ini.json"),
        "transform": _file_meta(sd / "transform.json"),
    }

def _inputs_meta(ver: str) -> Dict[str, Any]:
    return {
        "mame_xml": _file_meta(mame_xml_path(ver)),
        "history_xml": _file_meta(history_xml_path(ver)),
        "ini": {
            "game_status": _file_meta(ini_game_path(ver)),
            "category":    _file_meta(ini_category_path(ver)),
            "type":        _file_meta(ini_type_path(ver)),
        }
    }

def _outputs_meta(ver: str) -> Dict[str, Any]:
    return {
        "intermediate": {
            "mame_machines":       _file_meta(mame_machines_path(ver)),
            "mame_parent_index":   _file_meta(parent_index_path(ver)),
            "gh_system_ports":     _file_meta(gh_system_ports_path(ver)),
            "gh_ini_classifications": _file_meta(ini_classifications_path(ver)),
        },
        "final": {
            "exotica_lit_raw_data":     _file_meta(exotica_raw_path(ver)),
            "exotica_lit_wiki":         _file_meta(exotica_wiki_path(ver)),
            "wiki_pages_and_redirects": _file_meta(exotica_pages_path(ver)),
        }
    }

def _archives_listing(ver: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    ad = archives_dir(ver)
    if not ad.exists():
        return out
    for p in sorted(ad.iterdir()):
        if p.is_file():
            m = _file_meta(p)
            if m:
                out.append(m)
    return out

def _extracted_listing(ver: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    ed = extracted_dir(ver)
    if not ed.exists():
        return out
    for p in sorted(ed.iterdir()):
        if p.is_file():
            m = _file_meta(p)
            if m:
                out.append(m)
    return out

def _version_mismatch_note(vinfo: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compare numeric cores between MAME and GH/INI versions; return a small note block.
    """
    mame = vinfo.get("mame_xml_version") or vinfo.get("mame_build")
    hist = vinfo.get("history_version")
    ini_map = vinfo.get("ini_versions") or {}
    ini_versions = list(ini_map.values()) if isinstance(ini_map, dict) else []

    mismatch = False
    detail: List[str] = []

    # compare against all *provided* versions
    compare_set = [x for x in [hist, *ini_versions] if x]
    if mame and compare_set:
        for other in compare_set:
            if not _same_numeric_core(mame, other):
                mismatch = True
                detail.append(f"core(mame) != core({other})")

    return {"version_mismatch": mismatch, "details": detail} if mismatch else {"version_mismatch": False}

def _one_release(ver: str) -> Dict[str, Any]:
    paths = {
        "root": release_root(ver).as_posix(),
        "archives": archives_dir(ver).as_posix(),
        "extracted": extracted_dir(ver).as_posix(),
        "outputs": outputs_dir(ver).as_posix(),
        "summaries": summaries_dir(ver).as_posix(),
        "stamps": stamps_dir(ver).as_posix(),
    }
    vinfo = _read_versions_from_summaries(ver)
    entry = {
        "version": ver,
        "paths": paths,
        "archives": _archives_listing(ver),
        "extracted": _extracted_listing(ver),
        "inputs": _inputs_meta(ver),
        "outputs": _outputs_meta(ver),
        "summaries": _summaries_meta(ver),
        "stamps": _stamps_meta(ver),
        "versions": vinfo,
        "notes": _version_mismatch_note(vinfo),
    }
    return entry

# ---------- public API ----------

def refresh_releases_index() -> Dict[str, Any]:
    """
    Build and persist data/releases_index.json by scanning data/releases/*.
    Returns the JSON document as a dict.
    """
    root = DATA_DIR / "releases"
    versions = []
    if root.exists():
        for p in sorted(root.iterdir()):
            if p.is_dir():
                versions.append(p.name)

    doc = {
        "generated_at": _utc_now_iso(),
        "releases_root": root.as_posix(),
        "count": len(versions),
        "releases": [_one_release(v) for v in versions],
    }

    out_path = DATA_DIR / "releases_index.json"
    write_json(out_path, doc, sort_keys=False)
    return doc
