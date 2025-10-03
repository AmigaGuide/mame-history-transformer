from __future__ import annotations

from typing import Any, Dict, List, Optional

from mht.utils.chips import format_hz_3dp  # <-- import from chips

__all__ = [
    "orientation_from_rotate",
    "type_title",
    "format_hz_3dp",              # <-- re-export for convenience
    "build_displays_section",
    "displays_section_to_display",
]

def orientation_from_rotate(rot: Any) -> Optional[str]:
    """Map a numeric rotate value to 'Horizontal'/'Vertical'/None."""
    try:
        r = int(rot)
    except Exception:
        return None
    if r in (0, 180):
        return "Horizontal"
    if r in (90, 270):
        return "Vertical"
    return None

def type_title(s: Optional[str]) -> str:
    """Normalise display type to title-case with a few special cases."""
    s = (s or "").strip().lower()
    if s == "raster": return "Raster"
    if s == "vector": return "Vector"
    if s == "svg":    return "SVG"
    if s == "lcd":    return "LCD"
    return s.title() if s else ""

def _pluralise(singular: str, n: int, plural: Optional[str] = None) -> str:
    return singular if int(n or 0) == 1 else (plural or f"{singular}s")

def build_displays_section(displays: Optional[List[Dict[str, Any]]],
                           display_count: Optional[int]) -> Dict[str, Any]:
    """Group identical screen specs into tidy buckets."""
    disp_list = displays or []
    groups: Dict[tuple, int] = {}
    for d in disp_list:
        typ = type_title(d.get("type"))
        ori = orientation_from_rotate(d.get("rotate")) or ""
        hz_str = format_hz_3dp(d.get("refresh_hz"))
        w = h = None
        if typ in {"Raster", "LCD"}:
            try:
                w = int(d.get("width"))
                h = int(d.get("height"))
                if not (w > 0 and h > 0):
                    w = h = None
            except Exception:
                w = h = None
        key = (typ, ori, w, h, hz_str)
        groups[key] = groups.get(key, 0) + 1

    try:
        cnt = int(display_count) if display_count is not None else 0
    except Exception:
        cnt = 0
    if cnt <= 0:
        cnt = sum(groups.values())

    def _ord_key(kv):
        (typ, ori, w, h, hz) = kv[0]
        return (typ or "", ori or "", w or 0, h or 0, hz or "")

    grouped_list: List[Dict[str, Any]] = []
    for (typ, ori, w, h, hz), c in sorted(groups.items(), key=_ord_key):
        grouped_list.append({
            "count": c,
            "type": typ or "",
            "orientation": ori,
            "width": w,
            "height": h,
            "refresh": hz,
        })
    return {
        "heading": _pluralise("Screen", cnt),
        "count": cnt,
        "groups": grouped_list,
    }

def displays_section_to_display(section: Dict[str, Any]) -> str:
    """Render the grouped section into the multi-line display block."""
    lines: List[str] = []
    heading = section.get("heading") or "Screen"
    count = section.get("count") or 0
    lines.append(f"{heading}: {count}")
    for g in section.get("groups", []):
        c   = g.get("count", 1)
        typ = g.get("type", "")
        ori = g.get("orientation", "")
        w   = g.get("width")
        h   = g.get("height")
        hz  = g.get("refresh")
        type_label = typ + (f" ({ori})" if ori else "")
        if c > 1:
            lines.append(f"({c}x) {type_label}")
        else:
            lines.append(type_label)
        if w is not None and h is not None:
            lines.append(f"{w} x {h} pixels")
        if hz:
            lines.append(hz)
    return "\n".join(lines)
