from __future__ import annotations
from typing import Dict, Any, List

def _raw_mame_title(minfo: dict, fallback: str) -> str:
    return (minfo.get("description")
            or minfo.get("title")
            or minfo.get("fullname")
            or fallback)

def mame_titles_for_parent(parent_name: str,
                           mame: Dict[str, Any],
                           parent_index: Dict[str, Any]) -> list[dict]:
    out: list[dict] = []
    pinfo = mame.get(parent_name, {})
    out.append({
        "role": "parent",
        "machine": parent_name,
        "title": _raw_mame_title(pinfo, parent_name),
        "year": pinfo.get("year"),
    })
    clones = sorted((parent_index.get("parents") or {}).get(parent_name, []) or [])
    for c in clones:
        cinfo = mame.get(c, {})
        out.append({
            "role": "clone",
            "machine": c,
            "title": _raw_mame_title(cinfo, c),
            "year": cinfo.get("year"),
        })
    return out

def clone_entries_for_parent(parent_name: str,
                             mame: Dict[str, Any],
                             parent_index: Dict[str, Any]) -> List[dict]:
    clones = (parent_index.get("parents") or {}).get(parent_name, []) or []
    out: List[dict] = []
    for c in sorted(clones):
        minfo = mame.get(c, {})
        out.append({
            "machine": c,
            "title": _raw_mame_title(minfo, c),
            "year": minfo.get("year"),
        })
    return out

def render_mame_titles_display(rows: list[dict]) -> list[str]:
    if not isinstance(rows, list):
        return []
    parent_rows = [r for r in rows if str(r.get("role", "")).strip().lower() == "parent"]
    clone_rows  = [r for r in rows if str(r.get("role", "")).strip().lower() != "parent"]
    clone_rows.sort(key=lambda r: (
        (r.get("title") or "").casefold(),
        (r.get("machine") or "").casefold()
    ))
    ordered = parent_rows + clone_rows
    out: list[str] = []
    for r in ordered:
        title   = (r.get("title") or "").strip()
        year    = (r.get("year") or "")
        role    = str(r.get("role", "parent")).strip().lower() or "parent"
        machine = (r.get("machine") or "").strip()
        if not title:
            continue
        parts = [title]
        if str(year).strip():
            parts.append(f"({year})")
        parts.append(f"[{role}: {machine}]" if machine else f"[{role}]")
        out.append(" ".join(parts))
    return out
