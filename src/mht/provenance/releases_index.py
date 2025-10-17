from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Any, List, Optional
import datetime

from mht.utils.io import write_json, read_json
from mht.utils.paths import (
    DATA_DIR,
    releases_root,
    release_root,
    archives_dir,
    extracted_dir,
    outputs_dir,
    summaries_dir,
)
# Optional: we only read summaries if present
# mame:     summaries/mame_parsing_summary.json
# history:  summaries/history_parsing_summary.json
# ini:      summaries/ini_parsing_summary.json

def _size(p: Path) -> Optional[int]:
    try:
        return p.stat().st_size
    except FileNotFoundError:
        return None

def _mtime_iso(p: Path) -> Optional[str]:
    try:
        ts = p.stat().st_mtime
        return datetime.datetime.utcfromtimestamp(ts).isoformat() + "Z"
    except FileNotFoundError:
        return None

def _first_file_with_ext(d: Path, ext: str) -> Optional[Path]:
    if not d.exists():
        return None
    for p in sorted(d.iterdir()):
        if p.is_file() and p.suffix.lower() == ext.lower():
            return p
    return None

def _scan_archives(ver: str) -> Dict[str, Any]:
    a = archives_dir(ver)
    out: Dict[str, Any] = {"dir": a.as_posix(), "files": []}
    if not a.exists():
        return out
    for p in sorted(a.iterdir()):
        if p.is_file():
            out["files"].append({
                "name": p.name,
                "size": _size(p),
                "modified_utc": _mtime_iso(p),
            })
    return out

def _scan_extracted(ver: str) -> Dict[str, Any]:
    e = extracted_dir(ver)
    res = {
        "dir": e.as_posix(),
        "present": e.exists(),
        "mame_xml": None,
        "history_xml": None,
        "ini_files": [],
    }
    if not e.exists():
        return res
    mame = e / "mame.xml"
    hist = e / "history.xml"
    res["mame_xml"] = {"present": mame.exists(), "size": _size(mame), "modified_utc": _mtime_iso(mame)}
    res["history_xml"] = {"present": hist.exists(), "size": _size(hist), "modified_utc": _mtime_iso(hist)}
    for name in (
        "[GAMING HISTORY] Game Or No Game.ini",
        "[GAMING HISTORY] Machine Category.ini",
        "[GAMING HISTORY] Machine Type.ini",
    ):
        p = e / name
        res["ini_files"].append({"name": name, "present": p.exists(), "size": _size(p), "modified_utc": _mtime_iso(p)})
    return res

def _scan_outputs(ver: str) -> Dict[str, Any]:
    o = outputs_dir(ver)
    fields = [
        "mame_machines.json",
        "mame_parent_index.json",
        "gh_system_ports.json",
        "gh_ini_classifications.json",
        "exotica_lit_wiki.json",
        "exotica_lit_raw_data.json",
        "exotica_wiki_pages_and_redirects.json",
    ]
    out = {"dir": o.as_posix(), "files": []}
    if not o.exists():
        return out
    for f in fields:
        p = o / f
        out["files"].append({"name": f, "present": p.exists(), "size": _size(p), "modified_utc": _mtime_iso(p)})
    return out

def _read_versions_from_summaries(ver: str) -> Dict[str, Any]:
    sdir = summaries_dir(ver)
    data: Dict[str, Any] = {
        "mame_xml_version": None,
        "history_version": None,
        "history_date": None,
        "ini_versions": {},
    }
    # mame
    mp = sdir / "mame_parsing_summary.json"
    m = read_json(mp) or {}
    mv = (m.get("header", {}).get("versions") or {})
    data["mame_xml_version"] = mv.get("mame_xml_version") or mv.get("mame_build")
    # history
    hp = sdir / "history_parsing_summary.json"
    h = read_json(hp) or {}
    hv = (h.get("header", {}).get("versions") or {})
    data["history_version"] = hv.get("gh_version")
    data["history_date"]    = hv.get("gh_date")
    # ini
    ip = sdir / "ini_parsing_summary.json"
    i = read_json(ip) or {}
    ini_files = []
    # try a couple shapes the code already supports
    ini_root = (i.get("ini") or {}) if isinstance(i, dict) else {}
    files_node = ini_root.get("files")
    if isinstance(files_node, dict):
        for item in files_node.values():
            fn = (item.get("filename") or item.get("path") or "").strip()
            v  = item.get("version") or {}
            ver = v.get("mame_version") or v.get("raw") or "Unknown"
            if fn:
                data["ini_versions"][fn] = ver
    elif isinstance(i.get("files"), list):
        for item in i["files"]:
            fn = (item.get("filename") or item.get("path") or "").strip()
            v  = item.get("version") or {}
            ver = v.get("mame_version") or v.get("raw") or "Unknown"
            if fn:
                data["ini_versions"][fn] = ver
    return data

def build_release_record(ver: str) -> Dict[str, Any]:
    root = release_root(ver)
    return {
        "version": ver,
        "root": root.as_posix(),
        "exists": root.exists(),
        "archives": _scan_archives(ver),
        "extracted": _scan_extracted(ver),
        "outputs": _scan_outputs(ver),
        "versions": _read_versions_from_summaries(ver),
        "summaries": {
            "dir": summaries_dir(ver).as_posix(),
            "files": [
                {"name": "mame_parsing_summary.json", "present": (summaries_dir(ver) / "mame_parsing_summary.json").exists()},
                {"name": "history_parsing_summary.json", "present": (summaries_dir(ver) / "history_parsing_summary.json").exists()},
                {"name": "ini_parsing_summary.json", "present": (summaries_dir(ver) / "ini_parsing_summary.json").exists()},
                {"name": "transform_summary.json", "present": (summaries_dir(ver) / "transform_summary.json").exists()},
                {"name": "run_manifest.json", "present": (summaries_dir(ver) / "run_manifest.json").exists()},
            ],
        },
        "indexed_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

def rebuild_releases_index() -> List[Dict[str, Any]]:
    rr = releases_root()
    entries: List[Dict[str, Any]] = []
    if rr.exists():
        for child in sorted(rr.iterdir()):
            if child.is_dir():
                entries.append(build_release_record(child.name))
    write_json(DATA_DIR / "releases_index.json", entries, sort_keys=False)
    return entries
