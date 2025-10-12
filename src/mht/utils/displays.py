"""
Display extraction and QA helpers for MAME <machine> nodes.

Includes:
- extract_displays_for_parser(): builds the per-machine 'displays' list with
  validation rules identical to the original parser.
- extend_examples_capped(): utility to cap dropped-display example logs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from xml.etree.ElementTree import Element

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

        # Dimensions are meaningful only for raster-like displays
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
        group: Dict[str, Any] = {
            "count": c,
            "type": typ or "",
            "orientation": ori,
            "refresh": hz,
        }

        # Only include pixel dimensions for raster-like displays
        if (typ in {"Raster", "LCD"}) and (w is not None and h is not None):
            group["width"] = w
            group["height"] = h
        # For SVG/Vector, leave width/height absent (schema forbids them)

        grouped_list.append(group)

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
        lines.append(f"({c}x) {type_label}" if c > 1 else type_label)

        # Only show pixel dimensions for raster-like displays
        if typ in ("Raster", "LCD") and w is not None and h is not None:
            lines.append(f"{w} x {h} pixels")

        if hz:
            lines.append(hz)
    return "\n".join(lines)

def extract_displays_for_parser(machine_elem: Element, mame_name: str, *, max_examples: int = 10
                                ) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    """
    Extract and validate <display> nodes from a <machine> element.

    Behaviour is kept identical to the inlined logic previously in mame_parser:
    - Non-vector displays must have valid positive integer width/height, else they are dropped.
    - VECTOR displays are allowed without width/height.
    - rotate is parsed to int when numeric; otherwise None.
    - refresh is parsed to float when numeric; otherwise None.
    - type/tag normalised to lower-case (type) and stripped text (tag), allowing None.
    - Returns both the display list and a small metrics bundle so the caller can
      update global counters and dropped-display tracking without changing semantics.

    Returns:
        displays_list: List[dict] with keys: tag, type, rotate, width, height, refresh_hz
        display_count: int
        metrics: {
            "types_overall": Dict[str,int],
            "tags_overall": Dict[str,int],
            "dropped_total": int,
            "dropped_examples": List[dict]
        }
    """
    displays_list: List[Dict[str, Any]] = []
    types_overall: Dict[str, int] = {}
    tags_overall: Dict[str, int] = {}
    dropped_total = 0
    dropped_examples: List[Dict[str, Any]] = []

    for d in machine_elem.findall("display"):
        d_type = (d.attrib.get("type") or "").strip().lower() or None
        d_tag = (d.attrib.get("tag") or "").strip() or None

        rot_attr = (d.attrib.get("rotate") or "").strip()
        d_rotate = int(rot_attr) if rot_attr.isdigit() else None

        w_attr = (d.attrib.get("width") or "").strip()
        h_attr = (d.attrib.get("height") or "").strip()
        d_width = int(w_attr) if w_attr.isdigit() else None
        d_height = int(h_attr) if h_attr.isdigit() else None

        r_attr = (d.attrib.get("refresh") or "").strip()
        try:
            d_refresh_hz = float(r_attr) if r_attr else None
        except ValueError:
            d_refresh_hz = None

        valid = True
        if d_type != "vector":
            if (
                d_width is None or d_height is None
                or not isinstance(d_width, int) or not isinstance(d_height, int)
                or d_width <= 0 or d_height <= 0
            ):
                valid = False

        if not valid:
            dropped_total += 1
            if len(dropped_examples) < max_examples:
                dropped_examples.append({
                    "machine": mame_name,
                    "type": d_type,
                    "width": d_width,
                    "height": d_height,
                    "tag": d_tag,
                })
            continue

        displays_list.append({
            "tag": d_tag,
            "type": d_type,
            "rotate": d_rotate,
            "width": d_width,
            "height": d_height,
            "refresh_hz": d_refresh_hz,
        })

        # Maintain the same overall counting behaviour (None -> "unknown")
        types_overall[d_type or "unknown"] = types_overall.get(d_type or "unknown", 0) + 1
        tags_overall[d_tag or "unknown"] = tags_overall.get(d_tag or "unknown", 0) + 1

    return displays_list, len(displays_list), {
        "types_overall": types_overall,
        "tags_overall": tags_overall,
        "dropped_total": dropped_total,
        "dropped_examples": dropped_examples,
    }

def extend_examples_capped(dst: List[Dict[str, Any]], new: List[Dict[str, Any]], cap: int = 10) -> None:
    """
    Extend `dst` with items from `new` without exceeding `cap` total items.

    Mutates `dst` in place. No return value.
    Behaviour mirrors the previous inlined logic in mame_parser:
    - If dst already at/over cap: do nothing.
    - Otherwise, append up to (cap - len(dst)) entries from `new`.
    """
    remaining = max(0, cap - len(dst))
    if remaining:
        dst.extend(new[:remaining])
