from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Any, Optional
import datetime
import hashlib

from mht.utils.io import write_json, read_json
from mht.utils.paths import (
    DATA_DIR,
    releases_root,
    release_root,
    archives_dir,
    extracted_dir,
    outputs_dir,
    summaries_dir,
    encodings_cache_path,
)

# Optional: we only read summaries if present
# mame:     summaries/mame_parsing_summary.json
# history:  summaries/history_parsing_summary.json
# ini:      summaries/ini_parsing_summary.json

def _as_posix_rel(p: Path) -> str:
    """
    Normalise a Path to a repo-relative posix path beginning with 'data/...'.
    Works across Windows/macOS/Linux and pytest temp dirs that prepend extra segments.
    """
    p = Path(p).resolve()
    data_resolved = Path(DATA_DIR).resolve()

    # 1) Try true relative-to DATA_DIR
    try:
        rel = p.relative_to(data_resolved)
        return (Path("data") / rel).as_posix()
    except Exception:
        pass

    # 2) Robust string fallback: find the last '/data/' segment and keep from there
    p_norm = str(p).replace("\\", "/")
    # normalise DATA_DIR too (may help future heuristics)
    data_norm = str(data_resolved).replace("\\", "/")

    # If p starts with DATA_DIR, strip it
    if p_norm.lower().startswith(data_norm.lower()):
        rel = p_norm[len(data_norm):].lstrip("/")
        return ("data/" + rel) if rel else "data"

    # Otherwise, locate the last '/data/' segment anywhere in the path
    idx = p_norm.lower().rfind("/data/")
    if idx != -1:
        return p_norm[idx + 1:]  # drop leading slash so it starts 'data/...'

    # 3) Last resort: return posix form (absolute)
    return p.as_posix()

def _as_data_rel(p: Path) -> str:
    """
    Return a 'data/…' POSIX path string for any file/dir under the project data root.
    Falls back to as_posix() if we can't relativize (shouldn't happen in this repo).
    """
    try:
        base = DATA_DIR.parent  # repo root (parent of 'data')
        rel = os.path.relpath(p, start=base)
        # Ensure forward slashes regardless of platform
        s = rel.replace("\\", "/")
        # Guard: enforce the 'data/' prefix if not present
        if not s.startswith("data/"):
            s = f"data/{s.lstrip('./')}"
        return s
    except Exception:
        return p.as_posix().replace("\\", "/")

def _normalize_posix(obj):
    if isinstance(obj, dict):
        return {k: _normalize_posix(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_posix(v) for v in obj]
    if isinstance(obj, str):
        # Convert any Windows-style backslashes to forward slashes
        return obj.replace("\\", "/")
    return obj

def _file_meta(p: Path) -> Dict[str, Any]:
    return {
        "path": p.as_posix(),
        "size_bytes": (p.stat().st_size if p.exists() and p.is_file() else None),
        "modified_utc": _mtime_iso(p),
    }


def _get_sha256(path: Path) -> str:
    """Compute SHA256 of the file at 'path'."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

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
    #ini_files = []
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

    created_utc = _mtime_iso(min(root.glob("*"), key=lambda p: p.stat().st_mtime)) if any(root.glob("*")) else None
    updated_utc = _mtime_iso(max(root.glob("*"), key=lambda p: p.stat().st_mtime)) if any(root.glob("*")) else None
    byte_size   = sum((f.stat().st_size for f in root.rglob("*") if f.is_file()), 0)

    dotted_version = f"0.{ver[1:]}"  # '0281' -> '0.281'

    encodings = encodings_cache_path(ver)
    encodings_data = None
    if encodings.exists():
        encodings_data = {
            "path": _as_posix_rel(encodings),
            "size_bytes": encodings.stat().st_size,
            "sha256": _get_sha256(encodings),
            "modified_utc": _mtime_iso(encodings),
        }

    return {
        "version": ver,
        "dotted_version": dotted_version,
        "created_utc": created_utc,
        "updated_utc": updated_utc,
        "byte_size": byte_size,
        "flags": {
            "archives": bool(list(archives_dir(ver).glob("*.zip"))),
            "summaries": bool(list(summaries_dir(ver).glob("*.json"))),
            "outputs": bool(list(outputs_dir(ver).glob("*.json"))),
            "encodings": bool(encodings_data),
            "stamps": (root / ".stamps").exists(),
        },
        "paths": {
            "root":      _as_posix_rel(root),
            "archives":  _as_posix_rel(archives_dir(ver)),
            "outputs":   _as_posix_rel(outputs_dir(ver)),
            "summaries": _as_posix_rel(summaries_dir(ver)),
            "stamps":    _as_posix_rel(root / ".stamps"),
            "encodings": encodings_data["path"] if encodings_data else None,
        },
        "archives": [
            {"path": _as_posix_rel(p), "size_bytes": p.stat().st_size}
            for p in archives_dir(ver).glob("*.zip")
        ],
        "encodings": encodings_data,
        "outputs": [
            {"path": _as_posix_rel(p), "size_bytes": p.stat().st_size}
            for p in outputs_dir(ver).glob("*.json")
        ],
        "summaries": [
            {"name": p.name, "path": _as_posix_rel(p), "size_bytes": p.stat().st_size}
            for p in summaries_dir(ver).glob("*.json")
        ],
        "versions": _read_versions_from_summaries(ver),
        "notes": {},
        "indexed_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


def rebuild_releases_index() -> list[dict[str, Any]]:
    rr = releases_root()              # .../data/releases
    entries: list[dict[str, Any]] = []

    if rr.exists():
        for child in sorted(rr.iterdir()):
            if child.is_dir():
                entries.append(build_release_record(child.name))

    # Write next to the releases/ directory to avoid stale DATA_DIR bindings
    data_base = rr.parent             # .../data
    out_path = data_base / "releases_index.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(out_path, entries, sort_keys=False)

    return entries
