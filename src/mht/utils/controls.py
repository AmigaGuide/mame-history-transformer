from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

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
