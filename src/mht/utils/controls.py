from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from xml.etree.ElementTree import Element


__all__ = [
    "CONTROL_TYPE_LABELS",
    "pluralise",
    "control_type_label",
    "ways_pretty",
    "ways_label",
    "control_line_from_row",
    "buttons_count_from_rows",
    "build_controls_section",
    "controls_section_to_display",
]

CONTROL_TYPE_LABELS: Dict[str, str] = {
    "joy": "Joystick",
    "doublejoy": "Dual Joystick",
    "triplejoy": "Triple Joystick",
    "stick": "Analogue Joystick",
    "only_buttons": "Buttons Only",
    "paddle": "Paddle",
    "dial": "Dial",
    "trackball": "Trackball",
    "mouse": "Mouse",
    "positional": "Positional",
    "lightgun": "Light Gun",
    "pedal": "Pedal",
    "keyboard": "Keyboard",
    "keypad": "Keypad",
    "mahjong": "Mahjong Panel",
    "hanafuda": "Hanafuda Panel",
    "gambling": "Gambling Panel",
    # fallback: title-case of raw type
}

def pluralise(singular: str, n: int, plural: Optional[str] = None) -> str:
    try:
        count = int(n)
    except Exception:
        count = 0
    return singular if count == 1 else (plural or f"{singular}s")

def control_type_label(raw_type: Optional[str]) -> str:
    t = (raw_type or "").strip().lower()
    return CONTROL_TYPE_LABELS.get(t, t.title() if t else "Unknown Control")

def ways_pretty(raw: Optional[str]) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if s in {"vertical2", "strange2"}:
        return "2-way"
    # pattern like "8 (half16)"
    import re
    m = re.match(r"^(\d+)\s*\(half(\d+)\)$", s)
    if m:
        return f"{m.group(1)}-of-{m.group(2)}-way"
    if s.isdigit():
        return f"{int(s)}-way"
    # fall back to original (preserve caller’s spacing)
    return (raw or "").strip()

def ways_label(ways: Optional[str], ways2: Optional[str], ways3: Optional[str]) -> str:
    parts = [p for p in map(ways_pretty, (ways, ways2, ways3)) if p]
    return ", ".join(parts)

def control_line_from_row(row: Dict[str, Any]) -> str:
    typ = control_type_label(row.get("type"))
    w = ways_label(row.get("ways"), row.get("ways2"), row.get("ways3"))
    return f"{w} {typ}".strip() if w else typ

def buttons_count_from_rows(rows: List[Dict[str, Any]]) -> int:
    total = 0
    for r in rows or []:
        try:
            n = int(r.get("buttons")) if r.get("buttons") is not None else 0
        except Exception:
            n = 0
        total += max(0, n)
    return total

def build_controls_section(players: Optional[int], controls: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    # normalise player count
    try:
        pcount = int(players) if players is not None else 0
    except Exception:
        pcount = 0

    # group rows by player (default 1 if missing/invalid)
    bucket: Dict[int, List[Dict[str, Any]]] = {}
    for row in (controls or []):
        try:
            p = int(row.get("player"))
        except Exception:
            p = 1
        bucket.setdefault(p, []).append(row)

    per_player: List[Dict[str, Any]] = []
    for p in sorted(bucket.keys()):
        rows = bucket[p]
        raw_lines = [control_line_from_row(r) for r in rows]
        counts = Counter(l.casefold() for l in raw_lines)
        # keep first-seen order
        order = list(dict.fromkeys(raw_lines))
        control_lines = [
            (f"({counts[l.casefold()]}x) {l}" if counts[l.casefold()] > 1 else l)
            for l in order
        ]
        btn_total = buttons_count_from_rows(rows)
        per_player.append({"player": p, "control_lines": control_lines, "buttons": btn_total})

    def _placeholder(p: int) -> Dict[str, Any]:
        return {"player": p, "control_lines": ["Unknown controls"], "buttons": 0}

    if not per_player:
        if pcount > 0:
            per_player = [_placeholder(p) for p in range(1, pcount + 1)]
            return {"players": pcount, "per_player": per_player}
        return {"players": 0, "per_player": []}

    if pcount > 0:
        present = {e["player"] for e in per_player}
        for p in range(1, pcount + 1):
            if p not in present:
                per_player.append(_placeholder(p))
        per_player.sort(key=lambda e: e["player"])

    return {"players": pcount, "per_player": per_player}

def controls_section_to_display(section: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"Players: {section.get('players', 0)}")
    for pp in section.get("per_player", []):
        lines.append(f"Player {pp.get('player')}")
        for l in (pp.get("control_lines") or []):
            lines.append(l)
        btns = int(pp.get("buttons") or 0)
        lines.append("No Buttons" if btns <= 0 else f"{btns} {pluralise('Button', btns)}")
    return "\n".join(lines)

def extract_controls_for_parser(input_el: Element | None) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, int]]]:
    """
    Extract <control> entries from an <input> element and return:
      - controls_list: list of dicts with keys:
        player, type, buttons, reqbuttons, ways, ways2, ways3
      - metrics: per-field overall counters to merge at the caller:
        {
          "type_overall": Dict[str,int],
          "ways_overall": Dict[str,int],
          "ways2_overall": Dict[str,int],
          "ways3_overall": Dict[str,int],
          "buttons_overall": Dict[str,int],
          "reqbuttons_overall": Dict[str,int],
        }

    Behaviour mirrors the original in mame_parser:
    - type lowercased; empty → None in the per-control dict.
    - numeric fields parsed when digits; else None in the per-control dict.
    - overall counters use "unknown" for None/empty values.
    """
    controls_list: List[Dict[str, Any]] = []
    metrics = {
        "type_overall": {},
        "ways_overall": {},
        "ways2_overall": {},
        "ways3_overall": {},
        "buttons_overall": {},
        "reqbuttons_overall": {},
    }
    if input_el is None:
        return controls_list, metrics

    def _count(bucket: Dict[str, int], key: str | None):
        k = (key or "unknown")
        bucket[k] = bucket.get(k, 0) + 1

    for ctrl in input_el.findall("control"):
        c_type = (ctrl.attrib.get("type") or "").strip().lower() or None

        player_attr = (ctrl.attrib.get("player") or "").strip()
        c_player = int(player_attr) if player_attr.isdigit() else None

        buttons_attr = (ctrl.attrib.get("buttons") or "").strip()
        c_buttons = int(buttons_attr) if buttons_attr.isdigit() else None

        reqbuttons_attr = (ctrl.attrib.get("reqbuttons") or "").strip()
        c_reqbuttons = int(reqbuttons_attr) if reqbuttons_attr.isdigit() else None

        c_ways = (ctrl.attrib.get("ways") or "").strip() or None
        c_ways2 = (ctrl.attrib.get("ways2") or "").strip() or None
        c_ways3 = (ctrl.attrib.get("ways3") or "").strip() or None

        controls_list.append({
            "player": c_player,
            "type": c_type,
            "buttons": c_buttons,
            "reqbuttons": c_reqbuttons,
            "ways": c_ways,
            "ways2": c_ways2,
            "ways3": c_ways3,
        })

        _count(metrics["type_overall"], c_type)
        _count(metrics["ways_overall"], (c_ways or "").lower() or None)
        _count(metrics["ways2_overall"], (c_ways2 or "").lower() or None)
        _count(metrics["ways3_overall"], (c_ways3 or "").lower() or None)
        _count(metrics["buttons_overall"], str(c_buttons) if c_buttons is not None else None)
        _count(metrics["reqbuttons_overall"], str(c_reqbuttons) if c_reqbuttons is not None else None)

    return controls_list, metrics
