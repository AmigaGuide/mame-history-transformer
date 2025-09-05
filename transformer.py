"""
Filename: transformer.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Transforms parsed artefacts into a Wiki-ready dataset.

Phase 1 (this file): Parent/clone selection based on INI classifications + Title parsing.
- Keep parents where INI: game_status == "game" AND category includes "Arcade".
- Include ALL clones of those parents (even if clone classifications are unknown).
- Parse titles per spec: titles/subtitles/versions/global_version (numbered fields).
- Do NOT use 'type' to filter (kept for description only).
- Do NOT filter isbios/isdevice/ismechanical; just report any that appear post-filter.

Inputs:
- output/mame_machines.json
- output/gh_ini_classifications.json
- output/mame_parent_index.json

Outputs:
- output/exotica_lit_wiki.json        (Wiki-ready, no Ports yet; includes parsed description object)
- data/transform_summary.json         (counts, QA diagnostics, uncapped title anomaly examples)

Returns:
- True on success, False otherwise.
"""

from pathlib import Path
from typing import Dict, Any, Optional, Set, List, Tuple, Sequence, Iterable
import json
import datetime
import time
import re
from collections import Counter

from config import LOG_LEVEL
from logger import setup_logger, debug_log

log = setup_logger(log_level=LOG_LEVEL)

# --- Schemas (bump only when shapes change) ---
TRANSFORMER_SCHEMA = "0.5"   # used in data/transform_summary.json
WIKI_SCHEMA        = "1.0"   # used in exotica_lit_wiki.json header

DATA_DIR   = Path("data")
OUTPUT_DIR = Path("output")
WIKI_PREFIX = "Lost In Translation/"

#--- Input ---
MAME_MACHINES_PATH   = OUTPUT_DIR / "mame_machines.json"
INI_CLASS_PATH       = OUTPUT_DIR / "gh_ini_classifications.json"
PARENT_INDEX_PATH    = OUTPUT_DIR / "mame_parent_index.json"
GH_SYSTEM_PORTS_PATH = OUTPUT_DIR / "gh_system_ports.json"

#--- Output ---
WIKI_OUT_PATH             = OUTPUT_DIR / "exotica_lit_wiki.json"
RAW_OUT_PATH              = OUTPUT_DIR / "exotica_lit_raw_data.json"
TRANS_SUMMARY_PATH        = DATA_DIR / "transform_summary.json"
WIKI_PAGES_REDIRECTS_PATH = OUTPUT_DIR / "exotica_wiki_pages_and_redirects.json"

_ALNUM = re.compile(r"[A-Za-z0-9]")
_INFIX_RE = re.compile(r"[A-Za-z0-9]\([^()\[\]]+\)[A-Za-z0-9]")
_VERSION_CORE_RX = re.compile(r"\d+(?:\.\d+)+")

# Display precedence for the “Plus:” line (higher = earlier).
_MEDIA_ORDER = {
    "GD-ROM": 100,
    "DVD-ROM": 90,
    "CD-ROM": 80,
    "LaserDisc": 70,
    "Capacitance Electronic Disc (CED)": 60,
    "Hard disk": 50,
    "CompactFlash card": 40,
    "Secure Digital card": 30,
    "NAND flash": 20,
    "USB storage": 10,
    "VHS tape": 0,
}

_CONTROL_TYPE_LABELS = {
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
    # fallback → title-case of raw type
}

_TERMINAL_PUNCT = ('.', '!', '?', '…')

def _format_models_bracketed(models: list[str] | None) -> str:
    """Return '[A, B]' or '' (no leading space)."""
    models = [m.strip() for m in (models or []) if isinstance(m, str) and m.strip()]
    return f"[{', '.join(models)}]" if models else ""


def _title_case_words(s: str) -> str:
    return " ".join(w[:1].upper() + w[1:].lower() if w else w for w in (s or "").split())

def _format_regions(regs: list[str] | None) -> str:
    regs = regs or ["??"]
    regs = [r.strip() for r in regs if isinstance(r, str) and r.strip()]
    regs = regs or ["??"]
    return "".join(f"[{r}]" for r in regs)

def _format_additional_tags(tags: list[str] | None) -> str:
    tags = [t.strip() for t in (tags or []) if isinstance(t, str) and t.strip()]
    return f" [{', '.join(tags)}]" if tags else ""

def _format_models(models: list[str] | None) -> str:
    models = [m.strip() for m in (models or []) if isinstance(m, str) and m.strip()]
    return f" [{', '.join(models)}]" if models else ""

def _append_provenance_comment(existing: str | None, is_parent_row: bool, machine: str) -> str:
    role = "parent" if is_parent_row else "clone"
    prov = f"This GH port entry is based on the MAME {role} {machine}."
    c = (existing or "").strip()
    if c:
        if c.endswith(_TERMINAL_PUNCT):
            return f"{c} {prov}"
        else:
            return f"{c}. {prov}"
    else:
        return prov  # caller will add the leading ' : ' separator


def _render_ports_display(parent_machine: str, ports_obj: dict) -> dict[str, list[str]]:
    """
    Build a wiki-friendly single-line view per category, preserving GH order.
    Row-level provenance is appended ONLY when a category mixes parent+clone rows.
    Returns: { DisplayCategory: [line, ...], ... }
    """
    if not isinstance(ports_obj, dict):
        return {}

    out: dict[str, list[str]] = {}

    # 1) Pre-scan categories to detect whether they mix parent+clone rows
    cat_roles: dict[str, set[str]] = {}  # raw_cat -> {'parent'} | {'clone'} | {'parent','clone'}

    def _scan_source(source: dict, role: str) -> None:
        cats = (source or {}).get("categories") or {}
        for cat_key, rows in cats.items():
            if rows:
                cat_roles.setdefault(cat_key, set()).add(role)

    if ports_obj.get("parent_source"):
        _scan_source(ports_obj["parent_source"], "parent")
    for cs in ports_obj.get("clone_sources") or []:
        _scan_source(cs, "clone")

    # 2) Inner renderer that respects GH order and applies the mixed-category rule
    def _render_source(source: dict, is_parent: bool) -> None:
        cats = (source or {}).get("categories") or {}
        for cat_key, rows in cats.items():
            disp_cat = _title_case_words(cat_key)
            bucket = out.setdefault(disp_cat, [])
            mixed = (cat_roles.get(cat_key) == {"parent", "clone"})

            for r in rows or []:
                # Extract and format fields
                regions = _format_regions(r.get("regions"))
                platform = (r.get("platform") or "").strip()
                tags = _format_additional_tags(r.get("additional_tags"))  # includes leading space if present
                title = (r.get("title") or "").strip()
                date = (r.get("date") or "").strip()
                publisher = (r.get("publisher") or "").strip()
                models_in = _format_models_bracketed(r.get("model"))      # "[A, B]" or ""
                machine = (r.get("machine") or "").strip()

                parts: list[str] = []

                # Regions first
                parts.append(regions)

                # Platform (+tags). If there is NO title but there IS a model, show model here.
                platform_seg = f"{platform}{tags}"
                if title:
                    parts.append(platform_seg)
                else:
                    parts.append(f"{platform_seg} {models_in}".strip())

                # Title (quoted). If title exists and model exists, include model INSIDE quotes.
                if title:
                    safe_title = title.replace('"', '\\"')
                    if models_in:
                        parts.append(f"\"{safe_title} {models_in}\"")
                    else:
                        parts.append(f"\"{safe_title}\"")

                # Date and publisher (if present)
                if date:
                    parts.append(f"({date})")
                if publisher:
                    parts.append(f"by {publisher}")

                left = " ".join(p for p in parts if p)

                # Comment + conditional provenance (only if category is mixed)
                comment = (r.get("comment") or "").strip()
                if mixed:
                    comment = _append_provenance_comment(comment, is_parent_row=is_parent, machine=machine)

                line = f"{left} : {comment}" if comment else left
                bucket.append(line)

    # Parent first, then clones — preserves GH order end-to-end
    if ports_obj.get("parent_source"):
        _render_source(ports_obj["parent_source"], is_parent=True)
    for cs in ports_obj.get("clone_sources") or []:
        _render_source(cs, is_parent=False)

    return out



def _read_gh_ports(path: Path) -> dict:
    data = _read_json(path)
    return data if isinstance(data, dict) else {}

def _is_valid_port_row(row: dict) -> bool:
    # Gatekeeper: platform must be a non-empty string
    plat = (row or {}).get("platform")
    return isinstance(plat, str) and plat.strip() != ""

def _norm_regions(regs) -> list[str]:
    # Empty -> ["??"]; otherwise keep as-is (GH already uses 2-char codes)
    if not regs:
        return ["??"]
    out = []
    for r in regs:
        if isinstance(r, str) and r.strip():
            out.append(r.strip())
    return out or ["??"]

def _norm_tags(tags) -> list[str]:
    # additional_tags: keep non-empty strings only
    out = []
    for t in (tags or []):
        if isinstance(t, str) and t.strip():
            out.append(t.strip())
    return out

def _collect_valid_ports_by_category(gh_entry: dict, source_machine: str) -> dict[str, list[dict]]:
    """
    Returns { category: [ normalised rows... ] }.
    Each row carries 'machine' provenance.
    """
    cats = {}
    ports = (gh_entry or {}).get("ports") or {}
    if not isinstance(ports, dict):
        return cats
    for cat, rows in ports.items():
        if not isinstance(rows, list):
            continue
        out_rows = []
        for r in rows:
            if not isinstance(r, dict) or not _is_valid_port_row(r):
                continue
            out_rows.append({
                "machine": source_machine,                     # provenance
                "platform": r.get("platform"),
                "regions": _norm_regions(r.get("regions")),
                "model": r.get("model") or [],
                "title": r.get("title"),
                "date": r.get("date"),
                "publisher": r.get("publisher"),
                "comment": r.get("comment"),
                "additional_tags": _norm_tags(r.get("additional_tags")),
            })
        if out_rows:
            cats[cat] = out_rows
    return cats

def _gh_keys_with_any_valid_ports(gh_ports: dict) -> set[str]:
    """All GH shortnames that have at least one valid row in any category."""
    out = set()
    for key, entry in gh_ports.items():
        cats = _collect_valid_ports_by_category(entry, key)
        if any(cats.values()):
            out.add(key)
    return out


def _build_ports_for_parent(parent: str,
                            parents_map: dict[str, list],
                            gh_ports: dict) -> tuple[dict | None, set[str], bool]:
    """
    Returns (ports_obj_or_None, clones_with_ports_set, parent_has_ports_bool).
    ports_obj = {
      "parent_source": { "machine": parent, "gh_id": <int or None>, "categories": {...} }   # only if any rows
      "clone_sources": [ { "machine": clone, "gh_id": <int or None>, "categories": {...} }, ... ]
    }
    """
    ports_obj: dict = {"clone_sources": []}
    clones_with_ports: set[str] = set()
    parent_has_ports = False

    # Parent source
    p_entry = gh_ports.get(parent)
    if isinstance(p_entry, dict):
        p_cats = _collect_valid_ports_by_category(p_entry, parent)
        if any(p_cats.values()):
            ports_obj["parent_source"] = {
                "machine": parent,
                "gh_id": p_entry.get("gh_id"),
                "categories": p_cats
            }
            parent_has_ports = True

    # Clone sources
    for clone in (parents_map.get(parent) or []):
        c_entry = gh_ports.get(clone)
        if not isinstance(c_entry, dict):
            continue
        c_cats = _collect_valid_ports_by_category(c_entry, clone)
        if any(c_cats.values()):
            ports_obj["clone_sources"].append({
                "machine": clone,
                "gh_id": c_entry.get("gh_id"),
                "categories": c_cats
            })
            clones_with_ports.add(clone)

    if not parent_has_ports and not ports_obj["clone_sources"]:
        return None, clones_with_ports, False

    return ports_obj, clones_with_ports, parent_has_ports



def _control_type_label(raw_type: str | None) -> str:
    t = (raw_type or "").strip().lower()
    return _CONTROL_TYPE_LABELS.get(t, t.title() if t else "Unknown Control")

def _ways_pretty(raw: str | None) -> str:
    """
    Turn ways/ways2/ways3 into user-friendly tokens.
    Examples:
      '8'            -> '8-way'
      '3 (half4)'    -> '3-of-4-way'
      '5 (half8)'    -> '5-of-8-way'
      'vertical2'    -> '2-way'
      'strange2'     -> '2-way'
    Fallbacks:
      - int-like strings -> '<N>-way'
      - otherwise return as-is.
    """
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if s in {"vertical2", "strange2"}:
        return "2-way"
    # half patterns
    m = re.match(r"^(\d+)\s*\(half(\d+)\)$", s)
    if m:
        return f"{m.group(1)}-of-{m.group(2)}-way"
    # plain integer?
    if s.isdigit():
        return f"{int(s)}-way"
    return raw.strip()

def _ways_label(ways: str | None, ways2: str | None, ways3: str | None) -> str:
    parts = [p for p in map(_ways_pretty, (ways, ways2, ways3)) if p]
    return ", ".join(parts)

def _control_line_from_row(row: dict) -> str:
    """
    Line describing the controller itself (without buttons), e.g.:
      '4-way Joystick'
      '2-way, 8-way Dual Joystick'
      'Trackball'
    """
    typ = _control_type_label(row.get("type"))
    ways = _ways_label(row.get("ways"), row.get("ways2"), row.get("ways3"))
    return f"{ways} {typ}".strip() if ways else typ

def _buttons_count_from_rows(rows: list[dict]) -> int:
    """Sum 'buttons' across a player's rows; ignore reqbuttons per your call."""
    total = 0
    for r in rows:
        try:
            n = int(r.get("buttons")) if r.get("buttons") is not None else 0
        except Exception:
            n = 0
        total += max(0, n)
    return total



def _pluralise(singular: str, n: int, plural: str | None = None) -> str:
    return singular if n == 1 else (plural or f"{singular}s")

def _orientation_from_rotate(rot) -> str | None:
    try:
        r = int(rot)
    except Exception:
        return None
    if r in (0, 180):
        return "Horizontal"
    if r in (90, 270):
        return "Vertical"
    return None  # unknown/odd but harmless

def _type_title(s: str | None) -> str:
    s = (s or "").strip().lower()
    if s == "raster": return "Raster"
    if s == "vector": return "Vector"
    if s == "svg":    return "SVG"
    if s == "lcd":    return "LCD"
    return s.title() if s else ""

def _format_hz_3dp(hz) -> str | None:
    try:
        v = float(hz)
    except Exception:
        return None
    if v <= 0:
        return None
    return f"{v:.3f} Hz"


def _build_controls_section(players: int | None, controls: list[dict] | None) -> dict:
    """
    Returns:
    {
      "players": <int>,
      "per_player": [
        {"player": 1, "control_lines": ["4-way Joystick"], "buttons": 1},
        ...
      ]
    }
    """
    try:
        pcount = int(players) if players is not None else 0
    except Exception:
        pcount = 0

    bucket: dict[int, list[dict]] = {}
    for row in (controls or []):
        try:
            p = int(row.get("player"))
        except Exception:
            p = 1
        bucket.setdefault(p, []).append(row)

    per_player = []
    for p in sorted(bucket.keys()):
        rows = bucket[p]

        # Build control lines and collapse duplicates with (Nx)
        raw_lines = [_control_line_from_row(r) for r in rows]
        counts = Counter(l.casefold() for l in raw_lines)
        order = list(dict.fromkeys(raw_lines))  # preserve first-seen casing/order
        control_lines = [(f"({counts[l.casefold()]}x) {l}" if counts[l.casefold()] > 1 else l)
                         for l in order]

        # Buttons: sum across rows; show 'No Buttons' if zero
        btn_total = _buttons_count_from_rows(rows)

        per_player.append({
            "player": p,
            "control_lines": control_lines,
            "buttons": btn_total
        })

    return {"players": pcount, "per_player": per_player}


def _controls_section_to_display(section: dict) -> str:
    """
    Format:
      Players: N
      Player 1
      <each control line>
      <Buttons line>
      Player 2
      ...
    """
    lines: list[str] = []
    lines.append(f"Players: {section.get('players', 0)}")

    for pp in section.get("per_player", []):
        lines.append(f"Player {pp.get('player')}")
        for l in (pp.get("control_lines") or []):
            lines.append(l)
        btns = int(pp.get("buttons") or 0)
        lines.append("No Buttons" if btns <= 0 else f"{btns} {_pluralise('Button', btns)}")

    return "\n".join(lines)




def _build_displays_section(displays: list[dict] | None, display_count: int | None):
    """
    Group identical screens by (type, orientation, width, height, refresh_3dp).
    Width/height are ignored for Vector/SVG (set to None in the grouping key).

    Returns:
    {
      "heading": "Screen"|"Screens",
      "count": <total_screens>,
      "groups": [
        {
          "count": n,
          "type": "Raster"|"Vector"|"SVG"|"LCD",
          "orientation": "Horizontal"|"Vertical"|"",
          "width": 320|None,
          "height": 224|None,
          "refresh": "59.640 Hz"|None
        },
        ...
      ]
    }
    """
    disp_list = displays or []
    groups: dict[tuple, int] = {}

    for d in disp_list:
        typ = _type_title(d.get("type"))
        ori = _orientation_from_rotate(d.get("rotate")) or ""

        hz_str = _format_hz_3dp(d.get("refresh_hz"))

        # Width/height only meaningful for Raster/LCD
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

    # total count: take MAME's display_count if sensible, otherwise sum of groups
    try:
        cnt = int(display_count) if display_count is not None else 0
    except Exception:
        cnt = 0
    if cnt <= 0:
        cnt = sum(groups.values())

    # stable order: by type, orientation, width, height, refresh string
    def _ord_key(kv):
        (typ, ori, w, h, hz) = kv[0]
        return (typ or "", ori or "", w or 0, h or 0, hz or "")

    grouped_list = []
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


def _displays_section_to_display(section: dict) -> str:
    lines: list[str] = []
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

        # Type + orientation (prefix multiplicity only if this *whole group* is duplicated)
        type_label = typ + (f" ({ori})" if ori else "")
        if c > 1:
            lines.append(f"({c}x) {type_label}")
        else:
            lines.append(type_label)

        # Resolution only for Raster/LCD (width/height present)
        if w is not None and h is not None:
            lines.append(f"{w} x {h} pixels")

        # Refresh if available
        if hz:
            lines.append(hz)

    return "\n".join(lines)


def _build_chips_section(chips: list[dict] | None,
                         sound_channels: int | None,
                         device_ref):
    """
    Return a structured 'chips' dict ready for JSON:

    {
      "cpus": {
        "heading": "CPU" | "CPUs",
        "count": <int>,
        "items": ["(2x) Motorola 68000 @ 12.000 MHz", ...]
      },
      "audio_chips": {
        "heading": "Audio Chip" | "Audio Chips",
        "count": <int>,
        "items": ["(2x) Yamaha YM2151 @ 3.580 MHz", "OKI MSM6295", ...]
      },
      "requires_samples": true|false,
      "audio_channels": <int or 0>,
      "speakers": <int or 0>
    }

    Rules:
    - Exclude 'Speaker' and 'Samples'/'Sample' from audio_chips list.
    - Count speakers separately in 'speakers'.
    - '(Nx)' multiplicity applied to identical labels.
    """
    cpu_labels_raw: list[str] = []
    audio_chip_labels_raw: list[str] = []
    speaker_count = 0

    for ch in (chips or []):
        typ = (ch.get("type") or "").strip().lower()
        name_raw = (ch.get("name") or "").strip()
        clk = ch.get("clock_hz")
        name_ci = name_raw.casefold()

        if typ == "cpu":
            cpu_labels_raw.append(_chip_label(name_raw, clk))
            continue

        if typ == "audio":
            if name_ci == "speaker":
                speaker_count += 1
                continue
            if name_ci in {"samples", "sample"}:
                # confirmation comes via requires_samples below
                continue
            audio_chip_labels_raw.append(_chip_label(name_raw, clk))
            continue

        # Unknown types ignored

    cpu_items = _prefix_multiples(cpu_labels_raw)
    audio_items = _prefix_multiples(audio_chip_labels_raw)

    # Headings use the pre-collapse counts for natural language
    cpu_heading = _pluralise("CPU", len(cpu_labels_raw))
    audio_heading = _pluralise("Audio Chip", len(audio_chip_labels_raw), "Audio Chips")

    # Channels/samples
    try:
        chn = int(sound_channels) if sound_channels is not None else 0
    except Exception:
        chn = 0
    requires_samples = _has_samples_flag(device_ref)

    return {
        "cpus": {
            "heading": cpu_heading,
            "count": len(cpu_labels_raw),
            "items": cpu_items,
        },
        "audio_chips": {
            "heading": audio_heading,
            "count": len(audio_chip_labels_raw),
            "items": audio_items,
        },
        "requires_samples": bool(requires_samples),
        "audio_channels": chn,
        "speakers": int(speaker_count),
    }



def _hz_to_human(n: int | float | None) -> tuple[float, str] | None:
    """1000-based Hz units. Returns (value, unit) or None; formatted later to 3dp."""
    if not n:
        return None
    try:
        v = float(n)
    except (TypeError, ValueError):
        return None
    if v < 1.0:
        return None
    GHz = 1_000_000_000.0
    MHz = 1_000_000.0
    kHz = 1_000.0
    if v >= GHz: return (v / GHz, "GHz")
    if v >= MHz: return (v / MHz, "MHz")
    if v >= kHz: return (v / kHz, "kHz")
    return (v, "Hz")


def _chip_label(name: str | None, clock_hz) -> str:
    """e.g. 'Zilog Z80 @ 3.870 MHz' or 'Yamaha YM2151' if no clock."""
    nm = (name or "").strip()
    h = _hz_to_human(clock_hz)
    return f"{nm} @ {h[0]:.3f} {h[1]}" if h else nm


def _prefix_multiples(labels: list[str]) -> list[str]:
    """
    Collapse duplicates with '(Nx)' per project style.
    - Case-insensitive counting
    - Preserve first-seen order/casing
    """
    labels = [l for l in labels if l]
    counts = Counter(l.casefold() for l in labels)
    first_seen_unique = list(dict.fromkeys(labels))
    out = []
    for lab in first_seen_unique:
        n = counts[lab.casefold()]
        out.append(f"({n}x) {lab}" if n > 1 else lab)
    return out


def _sum_device_speakers(device_ref) -> int:
    """Sum 'speaker' across device_ref entries. Non-int/missing treated as 0."""
    if not isinstance(device_ref, (list, tuple)):
        return 0
    total = 0
    for d in device_ref:
        try:
            total += int(d.get("speaker", 0))
        except Exception:
            continue
    return total


def _has_samples_flag(device_ref) -> bool:
    """True if any device_ref entry has samples == 'yes' (case-insensitive)."""
    if not isinstance(device_ref, (list, tuple)):
        return False
    for d in device_ref:
        s = (d.get("samples") or "").strip().lower()
        if s in {"yes", "true", "1", "y"}:
            return True
    return False


def _format_chips_and_audio_block(chips: list[dict] | None,
                                  sound_channels: int | None,
                                  device_ref) -> str:
    """
    Order and rules:
      CPU: ...
      Audio: ...                (exclude 'Speaker' and 'Samples'/'Sample')
      Requires additional samples   (if any device_ref[].samples == 'yes')
      Audio channels: N             (if N > 0)
      (Nx) Speaker                  (if any counted)

    - Multiplicity '(Nx)' applied to identical rendered labels (case-insensitive).
    - 'tag' is ignored entirely.
    """
    cpu_labels: list[str] = []
    audio_chip_labels: list[str] = []
    speaker_count = 0

    for ch in (chips or []):
        typ = (ch.get("type") or "").strip().lower()
        name_raw = (ch.get("name") or "").strip()
        clk = ch.get("clock_hz")

        # Normalise name for rules but preserve original casing in labels
        name_ci = name_raw.casefold()

        if typ == "cpu":
            cpu_labels.append(_chip_label(name_raw, clk))
            continue

        if typ == "audio":
            if name_ci == "speaker":
                # Count speakers; do not list as an audio chip
                speaker_count += 1
                continue
            if name_ci in {"samples", "sample"}:
                # Do not list as an audio chip; samples requirement is handled below
                continue
            # Regular audio chip/device
            audio_chip_labels.append(_chip_label(name_raw, clk))
            continue

        # Unknown types: ignore for now

    lines: list[str] = []

    if cpu_labels:
        lines.append("CPU: " + ", ".join(_prefix_multiples(cpu_labels)))

    if audio_chip_labels:
        lines.append("Audio: " + ", ".join(_prefix_multiples(audio_chip_labels)))

    # Samples requirement (from device_ref)
    if _has_samples_flag(device_ref):
        lines.append("Requires additional samples")

    # Report channel count if present
    try:
        chn = int(sound_channels) if sound_channels is not None else 0
    except Exception:
        chn = 0
    if chn > 0:
        lines.append(f"Audio channels: {chn}")

    # Speaker line at the very end
    if speaker_count > 0:
        lines.append(f"({speaker_count}x) Speaker")

    return "\n".join(lines)


def _order_media_labels(labels: list[str]) -> list[str]:
    """Sort labels by precedence, then A→Z as a stable tiebreaker."""
    # De-dupe while preserving first occurrence (defensive)
    labels = list(dict.fromkeys(labels))
    return sorted(
        labels,
        key=lambda s: ( -_MEDIA_ORDER.get(s, -1), s.casefold() )
    )

def _normalise_device_to_media(raw: str) -> str | None:
    """
    Map one MAME device token/path to a friendly media label.
    Returns None for non-media / maintenance / bus identifiers.
    """
    s = (raw or "").lower()

    # Tokenise for exact hits (cd, dvd, cf, etc.)
    tokens = set(re.findall(r"[a-z0-9_]+", s))

    # LaserDisc: explicit names, numeric-suffixed tokens, or known player models
    if (
        "laserdisc" in tokens
        or any(t.startswith("laserdisc") for t in tokens)   # <- handles 'laserdisc1', 'laserdisc2', etc.
        or re.search(r"\b(ld_)?(ldv1000|pr7820|pr8210a?|22vp932)\b", s)
    ):
        return "LaserDisc"

    # Capacitance Electronic Disc
    if "ced_videodisc" in tokens:
        return "Capacitance Electronic Disc (CED)"

    # GD-ROM (Sega)
    if "gdrom" in tokens:
        return "GD-ROM"
    
    # DVD family (e.g., 'dvdrom', 'dvdrom1', 'dvd', etc.)
    if {"dvdrom", "dvd"} & tokens or any(t.startswith("dvdrom") for t in tokens):
        return "DVD-ROM"

    # Compact Disc family:
    #  - exact tokens like 'cdrom', 'cd', 'audiocd', 'cdxa'
    #  - drive identifiers like 'cdrom1', 'cdrom2', ...
    #  - known ATAPI/SCSI model IDs already in your list
    if (
        {"cdrom", "cd", "audiocd", "cdxa", "xm3301", "cr589", "stvcd"} & tokens
        or any(t.startswith("cdrom") for t in tokens)
    ):
        return "CD-ROM"

    # Hard disks (IDE/SCSI)
    if {"hdd", "harddisk", "scsi_hdd_image"} & tokens or ":hdd" in s:
        return "Hard disk"

    # CompactFlash (via PC Card/ATA bridges too)
    if {"cf", "cfcard", "cflash", "ataflash", "taitocf", "taitopccard1", "taitopccard2", "pccard"} & tokens:
        return "CompactFlash card"

    # Secure Digital
    if {"sdcard", "internalsd"} & tokens:
        return "Secure Digital card"

    # NAND flash
    if "nand" in tokens:
        return "NAND flash"

    # USB storage
    if "usb" in tokens:
        return "USB storage"

    # VHS tape
    if "vhs" in tokens:
        return "VHS tape"

    # Everything else (runtime, install, recovery, disks, cycraft, buses, etc.) -> ignore
    return None


def _normalise_device_list_to_media(devs: Iterable[str] | str | None) -> list[str]:
    """Return de-duplicated friendly labels, preserving original order; ignore unknowns."""
    if devs is None:
        return []
    seq = devs if isinstance(devs, (list, tuple)) else [devs]

    out: list[str] = []
    seen: set[str] = set()
    for raw in seq:
        label = _normalise_device_to_media(str(raw))
        if not label:
            continue  # drop unknown/non-media entries
        key = label.casefold()
        if key not in seen:
            seen.add(key)
            out.append(label)
    return out



def join_with_ampersand(items: Sequence[str]) -> str:
    """Join items as: A; A & B; A, B & C (no trimming; upstream cleaned)."""
    n = len(items)
    if n == 0:
        return ""
    if n == 1:
        return items[0]
    if n == 2:
        return f"{items[0]} & {items[1]}"
    return f"{', '.join(items[:-1])} & {items[-1]}"

def _split_outside_parens(s: str) -> list[str]:
    """Split on '/' only when outside (...) groups. Leave content inside parens untouched."""
    parts, buf, depth = [], [], 0
    for ch in s or "":
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "/" and depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
        else:
            buf.append(ch)
    last = "".join(buf).strip()
    if last:
        parts.append(last)
    # Do not strip—inputs already cleaned upstream
    return parts

def _format_rom_block(rom_count: int, rom_bytes_total: int,
                      disk_required: str | None, disk_regions) -> str:
                          
    # Line 1
    line1 = f"{rom_count:,} ROM" + ("" if rom_count == 1 else "s")

    # Line 2
    total_bytes = int(rom_bytes_total or 0)
    human = _bytes_to_binary_human(total_bytes)
    line2 = f"{total_bytes:,} bytes" + (f" ({human[0]:.2f} {human[1]})" if human else "")

    # Line 3 — only if disk_required == "yes"; devices come from disk_regions[]
    line3 = None
    if (disk_required or "").lower() == "yes":
        # Build the full list (including duplicates) by normalising each raw entry
        seq = disk_regions if isinstance(disk_regions, (list, tuple)) else ([disk_regions] if disk_regions else [])
        all_labels: list[str] = []
        for raw in seq:
            lab = _normalise_device_to_media(str(raw))
            if lab:
                all_labels.append(lab)

        if all_labels:
            # Count case-insensitively, but preserve original label text
            counts = Counter(l.casefold() for l in all_labels)

            # Preserve first-seen identity for later stable precedence sorting
            first_seen_unique = list(dict.fromkeys(all_labels))

            # Apply your precedence sort
            ordered_unique = _order_media_labels(first_seen_unique)

            # Render with “(Nx)” prefix when N>1, per your style “(2x) CD-ROM”
            display_labels = []
            for lab in ordered_unique:
                n = counts[lab.casefold()]
                display_labels.append(f"({n}x) {lab}" if n > 1 else lab)

            line3 = f"Plus: {join_with_ampersand(display_labels)}"

    return "\n".join([line1, line2] + ([line3] if line3 else []))


def _bytes_to_binary_human(n: int) -> tuple[float, str] | None:
    """Return (value, unit) in KiB/MiB/GiB to 2dp, or None if < 1024 bytes."""
    if n is None:
        return None
    KB = 1024
    MB = 1024 ** 2
    GB = 1024 ** 3
    if n >= GB:
        return (n / GB, "GiB")
    if n >= MB:
        return (n / MB, "MiB")
    if n >= KB:
        return (n / KB, "KiB")
    return None

def format_manufacturers_for_wiki(raw: str | None) -> str:
    parts = [p.strip() for p in _split_outside_parens(raw or "") if p.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} & {parts[1]}"
    return f"{', '.join(parts[:-1])} & {parts[-1]}"

def _collapse_ws(s: str) -> str:
    """Collapse internal whitespace to single spaces; trim ends."""
    return " ".join((s or "").split())

def _pref(name: str, prefix: str = WIKI_PREFIX) -> str:
    """Prefix a page/redirect name with the LiT namespace."""
    return f"{prefix}{name}"

def _unit_count_from_desc(desc_fields: dict) -> int:
    """Return how many title units exist (based on titleN fields present)."""
    nums = []
    for k in desc_fields.keys():
        if k.startswith("title") and k[5:].isdigit():
            nums.append(int(k[5:]))
    return max(nums) if nums else 1

def _build_redirect_sources(desc_fields: dict, wiki_page_name: str) -> list[str]:
    """
    From parsed description, build redirect source names (UNPREFIXED).
    Rules:
      - For each unit i>=2: add Titlei; and Titlei: Subtitlei (if subtitle exists)
      - If unit1 has a subtitle: add 'Title1' (lazy search)
      - Drop anything equal (case-insensitive) to the final wiki_page_name
      - Collapse whitespace; preserve punctuation/diacritics
      - Case-insensitive de-duplication; preserve first-seen casing
    """
    sources: list[str] = []
    seen_ci: set[str] = set()

    def add(name: str):
        n = _collapse_ws(name)
        if not n:
            return
        if n.casefold() == (wiki_page_name or "").casefold():
            return
        ci = n.casefold()
        if ci not in seen_ci:
            seen_ci.add(ci)
            sources.append(n)

    n_units = _unit_count_from_desc(desc_fields)
    # Alt units
    for i in range(2, n_units + 1):
        ti = (desc_fields.get(f"title{i}") or "").strip()
        si = (desc_fields.get(f"subtitle{i}") or "").strip()
        if ti:
            add(ti)
            if si:
                add(f"{ti}: {si}")

    # Lazy form for unit1 if it has a subtitle
    t1 = (desc_fields.get("title1") or "").strip()
    s1 = (desc_fields.get("subtitle1") or "").strip()
    if t1 and s1:
        add(t1)

    return sources


def _raw_mame_title(minfo: dict, fallback: str) -> str:
    """Return the raw MAME title for a machine (no transformer overrides)."""
    return (minfo.get("description")
            or minfo.get("title")
            or minfo.get("fullname")
            or fallback)

def _mame_titles_for_parent(parent_name: str,
                            mame: Dict[str, Any],
                            parent_index: Dict[str, Any]) -> list[dict]:
    """
    Build the MAME titles list for a parent:
      [{"role": "parent"/"clone", "machine": shortname, "title": raw MAME title, "year": <as-is>}, ...]
    Parent row always comes first, followed by clones sorted by machine.
    """
    out: list[dict] = []

    # Parent row
    pinfo = mame.get(parent_name, {})
    out.append({
        "role": "parent",
        "machine": parent_name,
        "title": _raw_mame_title(pinfo, parent_name),
        "year": pinfo.get("year"),  # keep as-is, e.g. "198?" or "1980"
    })

    # Clone rows
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

def _wiki_page_name_from_desc(desc_fields: dict) -> str:
    """Build the wiki page name as 'Title: Subtitle' (or just 'Title' if no subtitle)."""
    title = (desc_fields.get("title1") or "").strip()
    subtitle = (desc_fields.get("subtitle1") or "").strip()
    return f"{title}: {subtitle}" if subtitle else title


def _clone_entries_for_parent(parent_name: str,
                              mame: Dict[str, Any],
                              parent_index: Dict[str, Any]) -> list[dict]:
    """
    Build the clone list for a given parent:
      [{"machine": <shortname>, "title": <raw MAME title>, "year": <as-is>}, ...]
    Always returns a list (possibly empty).
    """
    clones = (parent_index.get("parents") or {}).get(parent_name, []) or []
    out: list[dict] = []
    for c in sorted(clones):  # stable order
        minfo = mame.get(c, {})
        out.append({
            "machine": c,
            "title": _raw_mame_title(minfo, c),   # raw MAME title, no overrides
            "year": minfo.get("year"),            # as-is, e.g. "198?" or "1980"
        })
    return out


def _core(s: str | None) -> str | None:
    """Extract numeric core like '0.279' or '2.79' from a version string."""
    if not s:
        return None
    m = _VERSION_CORE_RX.search(s)
    return m.group(0) if m else None


# ----------------------------
# IO helpers
# ----------------------------

def _read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error(f"Failed to read {path}: {e}")
        return None


def _write_json(path: Path, obj: Any) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        log.info(f"Wrote {path}")
        return True
    except Exception as e:
        log.error(f"Failed to write {path}: {e}")
        return False


def _project_for_wiki(rec: dict) -> dict:
    """
    Site-facing: slim, preformatted fields only.
    Keep only what ExoticA will ingest or render.
    """
    out = {}
    # Always keep identification
    if rec.get("wiki_page_name"): out["wiki_page_name"] = rec["wiki_page_name"]
    if rec.get("year") is not None: out["year"] = rec["year"]
    if rec.get("manufacturer") is not None: out["manufacturer"] = rec["manufacturer"]

    # Preformatted convenience blocks (include only if present)
    for k in ("roms_display", "chips_display", "displays_display", "controls_display"):
        if rec.get(k): out[k] = rec[k]

    # Ports: wiki shows ONLY the single-line view
    if rec.get("ports_display"):
        out["ports_display"] = rec["ports_display"]

    # Optional: keep MAME titles table if the site will show it
    if rec.get("mame_titles"): out["mame_titles"] = rec["mame_titles"]

    return out


def _project_for_raw(machine: str, rec: dict) -> dict:
    """
    Review-facing: rich, structured, no preformatted strings.
    Include per-variable fields for inspection and future renderers.
    """
    out = {}

    # Identification & provenance
    out["machine"] = machine
    if rec.get("wiki_page_name"): out["wiki_page_name"] = rec["wiki_page_name"]
    if rec.get("mame_titles"): out["mame_titles"] = rec["mame_titles"]

    # Title parsing (full structured description)
    if rec.get("description"): out["description"] = rec["description"]

    # Year/manufacturer
    if rec.get("year") is not None: out["year"] = rec["year"]
    if rec.get("manufacturer") is not None: out["manufacturer"] = rec["manufacturer"]

    # ROM/media raw stats (carry raw inputs; skip roms_display)
    for k in ("rom_count", "rom_bytes_total", "disk_required", "disk_regions"):
        if k in rec: out[k] = rec[k]

    # Chips / displays / controls: keep structured only
    if rec.get("chips"): out["chips"] = rec["chips"]
    if rec.get("displays"): out["displays"] = rec["displays"]
    if rec.get("controls"): out["controls"] = rec["controls"]

    # Ports (structured, when present)
    if rec.get("ports"): out["ports"] = rec["ports"]

    # Classifications & flags (useful for QA)
    for k in ("game_status", "category", "type", "isbios", "isdevice", "ismechanical", "requires_samples"):
        if k in rec: out[k] = rec[k]

    return out


# ----------------------------
# Classification helpers
# ----------------------------

def _classify(machine: str, ini_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Return normalised classification for a machine using the INI aggregation map.
    Missing/empty fields become 'unknown' (category becomes ['unknown']).
    """
    row = ini_map.get(machine)
    if not row:
        return {"game_status": "unknown", "category": ["unknown"], "type": "unknown"}
    gs = row.get("game_status", "unknown") or "unknown"
    cat = row.get("category")
    if not isinstance(cat, list) or not cat:
        cat = ["unknown"]
    typ = row.get("type", "unknown") or "unknown"
    return {"game_status": gs, "category": cat, "type": typ}


def _is_eligible_parent(machine: str,
                        mame: Dict[str, Any],
                        ini_map: Dict[str, Dict[str, Any]]) -> bool:
    """
    Eligibility predicate for parent machines:
      - must not be a clone,
      - INI says game_status == 'game',
      - INI category includes 'Arcade'.
    """
    info = mame.get(machine, {})
    if info.get("cloneof"):
        return False
    c = _classify(machine, ini_map)
    return (c["game_status"] == "game") and ("Arcade" in c["category"])


def _build_final_set(eligible_parents: Set[str],
                     parent_index: Dict[str, Any]) -> Set[str]:
    """
    Expand the eligible parent set with ALL their clones using mame_parent_index.json.
    """
    final: Set[str] = set(eligible_parents)
    parents_map: Dict[str, list] = (parent_index or {}).get("parents", {})
    for p in sorted(eligible_parents):
        final.update(parents_map.get(p, []))
    return final


def _machine_title(m: Dict[str, Any], fallback: str) -> str:
    """Get a display title for a MAME record with sensible fallbacks."""
    return m.get("description") or m.get("title") or m.get("fullname") or fallback


def _truthy_flag(v) -> bool:
    """
    Normalise a variety of MAME booleanish forms to True/False.
    Accepts booleans, numbers, and strings like 'yes'/'no', '1'/'0', etc.
    """
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"1", "true", "yes", "y", "t"}:
            return True
        if s in {"0", "false", "no", "n", "f", ""}:
            return False
    return False


def _load_title_overrides(path: Path) -> dict:
    """
    Load optional title overrides:
      {
        "machine_name": {
          "description": "<replacement text>",
          "apply_if_unbalanced": true|false,
          "note": "why"
        },
        ...
      }
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning(f"Failed to read title overrides {path}: {e}")
        return {}


def _dedupe_anomalies_preferring_pre_override(anoms: dict) -> dict:
    """
    De-duplicate anomaly examples by (machine, example),
    preferring entries tagged pre_override=True when both exist.
    """
    out = {}
    for cat, items in anoms.items():
        seen = {}
        for it in items:
            key = (it.get("machine"), it.get("example"))
            prev = seen.get(key)
            if prev is None:
                seen[key] = it
            else:
                if it.get("pre_override") and not prev.get("pre_override"):
                    seen[key] = it
        out[cat] = list(seen.values())
    return out


# ----------------------------
# TITLE PARSING (fixed)
# ----------------------------

def _normalise_inside_group(s: str) -> Tuple[str, bool]:
    """Inside a bracket group, replace top-level ' - ' and ' / ' with ', '."""
    changed = False
    out = []
    dR = dS = 0
    i = 0
    while i < len(s):
        if dR == 0 and dS == 0:
            if s.startswith(" - ", i):
                out.append(", "); changed = True; i += 3; continue
            if s.startswith(" / ", i):
                out.append(", "); changed = True; i += 3; continue
        ch = s[i]
        if ch == "(": dR += 1
        elif ch == ")": dR = max(0, dR - 1)
        elif ch == "[": dS += 1
        elif ch == "]": dS = max(0, dS - 1)
        out.append(ch); i += 1
    return ("".join(out), changed)


def _top_level_groups(unit: str) -> List[Tuple[int, int, str, str]]:
    """
    Return top-level bracket groups in this unit:
    list of (start, end, bracket_type, content_normalised).
    Nested groups are preserved INSIDE content, not yielded separately.
    """
    groups = []
    dR = dS = 0
    i = 0
    while i < len(unit):
        ch = unit[i]
        if ch in "([":
            if dR == 0 and dS == 0:  # top-level group starts here
                start = i
                btype = ch
                # scan to its matching close, allowing nesting
                i += 1
                dR += (ch == "(")
                dS += (ch == "[")
                while i < len(unit) and (dR > 0 or dS > 0):
                    if unit[i] == "(": dR += 1
                    elif unit[i] == ")": dR -= 1
                    elif unit[i] == "[": dS += 1
                    elif unit[i] == "]": dS -= 1
                    i += 1
                end = i - 1  # index of the closing ) or ]
                raw = unit[start+1:end]
                content, _ = _normalise_inside_group(raw)
                groups.append((start, end, "(" if btype == "(" else "[", content))
                continue
        # advance normally
        i += 1
    return groups


def _first_trailing_start(unit: str, groups: List[Tuple[int,int,str,str]]) -> Optional[int]:
    """
    Find the start index of the FIRST top-level group that is a 'trailing' group:
    i.e., preceded by whitespace (so not infix like APE(X)C).
    """
    for (start, end, _, _) in groups:
        if start == 0:
            return start
        prev = unit[start - 1]
        if prev.isspace():
            return start
    return None


def _split_outside_tokens_after(unit: str, groups: List[Tuple[int,int,str,str]], from_index: int) -> List[str]:
    """
    Collect outside (non-bracket) token fragments AFTER from_index,
    skipping over bracket groups. Clean leading/trailing punctuation.
    """
    tokens: List[str] = []
    spans = [(s, e) for (s, e, _, _) in groups if s >= from_index]
    spans.sort()
    cursor = from_index
    for (s, e) in spans:
        if s > cursor:
            frag = unit[cursor:s].strip()
            if frag:
                tokens.append(_clean_token(frag))
        cursor = e + 1
    if cursor < len(unit):
        frag = unit[cursor:].strip()
        if frag:
            tokens.append(_clean_token(frag))
    return [t for t in tokens if t]


def _clean_token(t: str) -> str:
    """Trim and drop leading/trailing punctuation commonly used as separators."""
    t = t.strip()
    while t and t[0] in "-:,/;()[]":
        t = t[1:].lstrip()
    while t and t[-1] in "-:,/;()[]":
        t = t[:-1].rstrip()
    t = " ".join(t.split())
    return t


def _find_infix_brackets_no_spaces(s: str) -> bool:
    """Heuristic: bracket group immediately between alnum on both sides."""
    return _INFIX_RE.search(s) is not None


def _find_unbalanced(full: str) -> Tuple[bool, bool]:
    """Return (unbalanced_round, unbalanced_square) for a full string."""
    dR = dS = 0
    for ch in full:
        if ch == "(": dR += 1
        elif ch == ")": dR -= 1
        elif ch == "[": dS += 1
        elif ch == "]": dS -= 1
    return (dR != 0, dS != 0)


def _parse_unit(unit_text: str) -> Tuple[str, str, List[str], List[str], Dict[str, bool]]:
    """
    Parse ONE title unit:
      returns (base_title, subtitle, group_contents_in_order, outside_tokens_after_first_group, warn_flags)
      - Only top-level groups are returned in 'group_contents_in_order' (nested are inside).
      - 'outside_tokens_after_first_group' are non-bracket text fragments after the first group.
    """
    warn = {"odd_separator_usage": False}
    groups = _top_level_groups(unit_text)
    first_tr_start = _first_trailing_start(unit_text, groups)
    cut = first_tr_start if first_tr_start is not None else len(unit_text)
    head = unit_text[:cut]

    # Subtitle split on first ' - ' or ':' outside brackets
    sub_pos = None
    chosen = None
    for sep in (" - ", ":"):
        idx = head.find(sep)
        if idx != -1 and (sub_pos is None or idx < sub_pos):
            sub_pos = idx
            chosen = sep
    if sub_pos is not None:
        base = head[:sub_pos].strip()
        subtitle = head[sub_pos + len(chosen):].strip()
    else:
        base = head.strip()
        subtitle = ""

    # Determine if we normalised anything in groups (for warnings)
    for (_, _, _, content_raw) in groups:
        _, changed = _normalise_inside_group(content_raw)
        if changed:
            warn["odd_separator_usage"] = True
            break

    outside_tokens: List[str] = []
    if first_tr_start is not None:
        outside_tokens = _split_outside_tokens_after(unit_text, groups, from_index=groups[0][1] + 1)

    group_contents = [g[3].strip() for g in groups]
    return base, subtitle, group_contents, outside_tokens, warn


def _parse_description(full_desc: str) -> Tuple[Dict[str, str], Dict[str, List[Dict[str, str]]]]:
    """
    Build numbered title/subtitle/version fields + single 'global_version'.
    Returns (description_dict, anomalies_dict).
    """
    anomalies: Dict[str, List[Dict[str, str]]] = {
        "unbalanced_round_brackets": [],
        "unbalanced_square_brackets": [],
        "infix_brackets_no_spaces": [],
        "ambiguous_trailing_tokens": [],
        "odd_separator_usage": [],
    }

    # Global anomaly checks on the raw string
    unb_round, unb_square = _find_unbalanced(full_desc)
    if unb_round:  anomalies["unbalanced_round_brackets"].append({"example": full_desc})
    if unb_square: anomalies["unbalanced_square_brackets"].append({"example": full_desc})
    if _find_infix_brackets_no_spaces(full_desc):
        anomalies["infix_brackets_no_spaces"].append({"example": full_desc})

    # Split into title units outside brackets
    def split_top_level(text: str, delim: str) -> List[str]:
        out, buf = [], []
        dR = dS = 0
        i, L, dlen = 0, len(text), len(delim)
        while i < L:
            if dR == 0 and dS == 0 and text.startswith(delim, i):
                out.append("".join(buf)); buf = []; i += dlen; continue
            ch = text[i]
            if ch == "(": dR += 1
            elif ch == ")": dR = max(0, dR - 1)
            elif ch == "[": dS += 1
            elif ch == "]": dS = max(0, dS - 1)
            buf.append(ch); i += 1
        out.append("".join(buf))
        return out

    units = split_top_level(full_desc, " / ")

    unit_info = []
    total_top_groups = 0
    for u in units:
        base, sub, group_contents, outside_tokens, warn = _parse_unit(u)
        unit_info.append((base, sub, group_contents, outside_tokens, warn))
        total_top_groups += len(group_contents)
        if warn.get("odd_separator_usage"):
            anomalies["odd_separator_usage"].append({"example": full_desc})
        if outside_tokens:
            anomalies["ambiguous_trailing_tokens"].append({"example": full_desc})

    # Build numbered fields placeholders
    desc: Dict[str, str] = {}
    for idx in range(len(unit_info)):
        desc[f"title{idx+1}"] = ""
        desc[f"subtitle{idx+1}"] = ""
        desc[f"version{idx+1}"] = ""

    for idx, (base, sub, _, _, _) in enumerate(unit_info, start=1):
        desc[f"title{idx}"] = base
        desc[f"subtitle{idx}"] = sub

    # Decide global_version vs per-title versionN
    global_parts: List[str] = []
    if total_top_groups == 1:
        for (_, _, groups, outs, _) in unit_info:
            if groups:
                global_parts.append(groups[0])
                for t in outs:
                    global_parts.append(t)
                break
    else:
        for idx, (_, _, groups, outs, _) in enumerate(unit_info, start=1):
            if groups:
                desc[f"version{idx}"] = groups[0]
                for extra in groups[1:]:
                    global_parts.append(extra)
            for t in outs:
                global_parts.append(t)

    desc["global_version"] = ", ".join(p for p in global_parts if p)
    return desc, anomalies


# ----------------------------
# Main transform
# ----------------------------

def run_transformer(data_dir: Path = DATA_DIR) -> bool:
    started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    t0 = time.perf_counter()

    # Safe default for header; will be populated from summaries below
    wiki_header_versions = {
        "mame_xml_version": "Unknown",
        "gaming_history_xml_version": "Unknown",
        "ini_versions": {}
    }

    # Optional overrides
    overrides_path = DATA_DIR / "title_overrides.json"
    overrides = _load_title_overrides(overrides_path)
    have_overrides = isinstance(overrides, dict) and bool(overrides)

    overrides_applied: list[dict[str, str]] = []
    overrides_stats = {
        "configured": len(overrides),
        "eligible": 0,
        "applied": 0
    }

    # Load required inputs
    mame = _read_json(MAME_MACHINES_PATH)
    ini_map = _read_json(INI_CLASS_PATH)
    parent_index = _read_json(PARENT_INDEX_PATH)
    gh_ports = _read_gh_ports(GH_SYSTEM_PORTS_PATH)
    gh_keys_with_ports = _gh_keys_with_any_valid_ports(gh_ports)
    if not isinstance(mame, dict) or not isinstance(ini_map, dict) or not isinstance(parent_index, dict):
        log.error("Missing or invalid inputs; aborting transform.")
        return False


    # --- Read stage summaries (sources of truth for versions) ---
    mame_sum = _read_json(DATA_DIR / "mame_parsing_summary.json") or {}
    hist_sum = _read_json(DATA_DIR / "history_parsing_summary.json") or {}
    ini_sum  = _read_json(DATA_DIR / "ini_parsing_summary.json") or {}

    # Raw versions for the transform summary (audit only)
    versions = {
        "mame_build":      (mame_sum.get("mame")    or {}).get("build"),
        "history_version":  (hist_sum.get("history") or {}).get("version"),
        "history_date":     (hist_sum.get("history") or {}).get("date"),
        "ini_generated_at": (ini_sum.get("ini")      or {}).get("generated_at"),
    }

    # --- Build wiki header versions using creators' schemes (no mismatch reporting here) ---
    mame_build_raw   = (mame_sum.get("mame")    or {}).get("build")    # e.g. "0.279 (mame0279)"
    mame_core        = _core(mame_build_raw)                           # -> "0.279" or None
    hist_version_raw = (hist_sum.get("history") or {}).get("version")  # e.g. "2.79" / "2.79a"

    # Per-INI versions: tolerate current and older shapes
    ini_versions_raw: dict[str, str] = {}

    # Your current shape: { "ini": { "files": { "game_status": {...}, "category": {...}, "type": {...} } } }
    ini_root = (ini_sum.get("ini") or {}) if isinstance(ini_sum, dict) else {}
    files_node = ini_root.get("files")

    if isinstance(files_node, dict):
        for item in files_node.values():
            fn = (item.get("filename") or item.get("path") or "").strip()
            v  = item.get("version") or {}
            ver = v.get("mame_version") or v.get("raw") or "Unknown"
            if fn:
                ini_versions_raw[fn] = ver

    # Fallbacks for older/alternative shapes
    if not ini_versions_raw:
        # shape: { "files": [ {...}, {...} ] }
        files_list = ini_sum.get("files")
        if isinstance(files_list, list):
            for item in files_list:
                fn = (item.get("filename") or item.get("path") or "").strip()
                v  = item.get("version") or {}
                ver = v.get("mame_version") or v.get("raw") or "Unknown"
                if fn:
                    ini_versions_raw[fn] = ver

    if not ini_versions_raw:
        # stage-style: { "inputs": [ {...}, ... ] }
        for item in (ini_root.get("inputs") or ini_sum.get("inputs") or []):
            fn = (item.get("filename") or item.get("path") or "").strip()
            v  = item.get("version") or {}
            ver = v.get("mame_version") or v.get("raw") or "Unknown"
            if fn:
                ini_versions_raw[fn] = ver

    # Now build the header block
    wiki_header_versions = {
        "mame_xml_version":            mame_core or "Unknown",
        "gaming_history_xml_version":  hist_version_raw or "Unknown",  # keep GH style (e.g. "2.79a")
        "ini_versions":                {fn: (ini_versions_raw.get(fn) or "Unknown") for fn in ini_versions_raw}
    }


    # ---------------- Selection + Title parsing ----------------
    all_names = sorted(mame.keys())
    eligible_parents: Set[str] = {n for n in all_names if _is_eligible_parent(n, mame, ini_map)}
    included_parents: Set[str] = eligible_parents     # parents-only export

    out_map: Dict[str, Dict[str, Any]] = {}

    # Parent exclusion reasons (for info)
    excluded_reasons = {"not_game": 0, "not_arcade": 0, "unknown_classification": 0}

    # Flag tallies (now count PARENTS only)
    included_flags = {"isbios": 0, "isdevice": 0, "ismechanical": 0}

    # Track oddities while building records (e.g. parent listed in index but missing in mame map)
    missing_in_mame: List[str] = []

    # Title anomaly buckets (parents only, uncapped examples)
    title_anomalies: Dict[str, List[Dict[str, str]]] = {
        "unbalanced_round_brackets": [],
        "unbalanced_square_brackets": [],
        "infix_brackets_no_spaces": [],
        "ambiguous_trailing_tokens": [],
        "odd_separator_usage": [],
    }


    # --- Media label counters (parents only) ---
    media_label_counts: dict[str, int] = {}
    parents_with_any_media = 0

    # --- Audit: raw device strings we ignored (no known media mapping) ---
    ignored_device_counts: dict[str, int] = {}
    _IGNORED_TOP_N = 25  # change if you want more/less in the summary

    # --- Audio QA tallies (parents only) ---
    audio_total_with_channels = 0
    audio_channel_speaker_mismatch = 0
    audio_mismatch_examples: list[dict] = []   # keep small sample for summary
    audio_samples_required_count = 0

    # --- GH port tallies 
    parents_with_ports_count = 0
    clones_with_ports_set: set[str] = set()


    for name in sorted(included_parents):
        minfo = mame.get(name)
        if not minfo:
            continue  # defensive

        cls = _classify(name, ini_map)

        # Pre-override anomaly capture on ORIGINAL raw MAME title
        raw_desc_original = _machine_title(minfo, name)
        _, pre_anoms = _parse_description(raw_desc_original)
        for k, lst in pre_anoms.items():
            for item in lst:
                item["machine"] = name
                item["pre_override"] = True
            title_anomalies[k].extend(lst)

        # Optional override for parents only
        orig_unbalanced_round, orig_unbalanced_square = _find_unbalanced(raw_desc_original)
        ov = overrides.get(name)
        raw_desc = raw_desc_original
        if ov and isinstance(ov, dict):
            apply_if_unbalanced = bool(ov.get("apply_if_unbalanced", True))
            condition_met = (not apply_if_unbalanced) or orig_unbalanced_round or orig_unbalanced_square
            if condition_met:
                overrides_stats["eligible"] += 1
                new_desc = ov.get("description")
                if isinstance(new_desc, str) and new_desc.strip():
                    raw_desc = new_desc.strip()
                    overrides_applied.append({
                        "machine": name,
                        "from": raw_desc_original,
                        "to": raw_desc,
                        "reason": ov.get("note", "override")
                    })
                    overrides_stats["applied"] += 1

        # Parse (possibly overridden) title for wiki_page_name + keep parsed fields for reference
        desc_fields, _ = _parse_description(raw_desc)
        wiki_page_name = _wiki_page_name_from_desc(desc_fields)

        #raw_man = minfo.get("manufacturer")
        #manufacturer_display = format_manufacturers_for_wiki(raw_man)
        raw_man = minfo.get("manufacturer") or ""
        manufacturer_display = join_with_ampersand(_split_outside_parens(raw_man))

        # ROM summary (data already parsed upstream)
        rom_count       = int(minfo.get("rom_count") or 0)
        rom_bytes_total = int(minfo.get("rom_bytes_total") or 0)
        disk_required = minfo.get("disk_required")  # "yes" / "no"
        disk_regions  = minfo.get("disk_regions")   # list (per your schema)

        # Normalise raw device names to display media labels
        roms_display = _format_rom_block(rom_count, rom_bytes_total, disk_required, disk_regions)

        # Media label counting (parents only)
        if (str(disk_required or "").lower() == "yes"):
            labels_for_counts = _normalise_device_list_to_media(disk_regions)
            if labels_for_counts:
                parents_with_any_media += 1
                for lab in dict.fromkeys(labels_for_counts):  # de-dupe per parent
                    media_label_counts[lab] = media_label_counts.get(lab, 0) + 1
            else:
                log.debug(f"[transformer::run_transformer] No media mapped for {name}; disk_regions={disk_regions!r}")


            # Audit: record any raw entries that didn't map to a known medium
            seq = disk_regions if isinstance(disk_regions, (list, tuple)) else ([disk_regions] if disk_regions else [])
            for raw in seq:
                if _normalise_device_to_media(str(raw)) is None:
                    ignored_device_counts[str(raw)] = ignored_device_counts.get(str(raw), 0) + 1
                    

        # --- Chips / Audio block + QA tallies ---
        chips_section = _build_chips_section(
            minfo.get("chips"),
            minfo.get("sound_channels"),
            minfo.get("device_ref"),
        )


        displays_section = _build_displays_section(
            minfo.get("displays"),
            minfo.get("display_count")
        )
        displays_display = _displays_section_to_display(displays_section)


        controls_section = _build_controls_section(
            minfo.get("players"),
            minfo.get("controls"),
        )
        controls_display = _controls_section_to_display(controls_section)



        reported_channels = minfo.get("sound_channels")
        speaker_sum = _sum_device_speakers(minfo.get("device_ref"))

        # Count machines where a channel count is reported (>0)
        try:
            chn = int(reported_channels) if reported_channels is not None else 0
        except Exception:
            chn = 0

        if chn > 0:
            audio_total_with_channels += 1
            if speaker_sum != chn:
                audio_channel_speaker_mismatch += 1
                if len(audio_mismatch_examples) < 10:  # cap examples in summary
                    audio_mismatch_examples.append({
                        "machine": name,
                        "sound_channels": chn,
                        "speaker_sum": speaker_sum
                    })

        # Samples required?
        if _has_samples_flag(minfo.get("device_ref")):
            audio_samples_required_count += 1


        parents_map: Dict[str, list] = (parent_index or {}).get("parents", {})  # you already build this earlier

        ports_obj, clones_with_ports_local, parent_has_ports = _build_ports_for_parent(name, parents_map, gh_ports)

        # Final inclusion gate: keep this parent only if parent or any clone has ports
        if ports_obj is None:
            continue

        # Accumulate summary tallies
        clones_with_ports_set.update(clones_with_ports_local)
        if parent_has_ports:
            parents_with_ports_count += 1


        record = {
            "wiki_page_name": wiki_page_name,
            "description": desc_fields,  # retained for QA/reference
            "year": minfo.get("year") if minfo.get("year") not in ("", None) else None,
            "manufacturer": manufacturer_display if manufacturer_display else None,
            # Preformatted
            "roms_display": roms_display, # e.g. "10 ROMs\n25,376 bytes (24.78 KiB)\nPlus: laserdisc"
            # Raw ROM/media stats
            "rom_count": rom_count,
            "rom_bytes_total": rom_bytes_total,
            "disk_required": disk_required,
            "disk_regions": disk_regions,
            
            "chips": chips_section,
            "displays": displays_section,        # NEW: machine-readable
            "displays_display": displays_display, # NEW: human block you asked for
            "controls": controls_section,          # machine-readable
            "controls_display": controls_display,  # human-readable now

            # Classifications (from INI)
            "game_status": cls["game_status"],
            "category": cls["category"],
            "type": cls["type"],

            # MAME flags (report-only)
            "isbios": _truthy_flag(minfo.get("isbios")),
            "isdevice": _truthy_flag(minfo.get("isdevice")),
            "ismechanical": _truthy_flag(minfo.get("ismechanical")),
            "requires_samples": _truthy_flag(minfo.get("requires_samples")),

            # NEW: preformatted titles table rows for wiki (parent first, then clones by machine)
            "mame_titles": _mame_titles_for_parent(name, mame, parent_index),
            
            "ports": ports_obj,
        }


        ports_display = _render_ports_display(name, ports_obj)
        if ports_display:
            record["ports_display"] = ports_display  # this will be kept only in the wiki projection

        # If you still tally flags, this now counts parents only
        if _truthy_flag(minfo.get("isbios")):       included_flags["isbios"] += 1
        if _truthy_flag(minfo.get("isdevice")):     included_flags["isdevice"] += 1
        if _truthy_flag(minfo.get("ismechanical")): included_flags["ismechanical"] += 1

        out_map[name] = record

    # --- Write wiki output (header + games) ---
    wiki_doc = {
        "header": {
            "versions": wiki_header_versions,
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "wiki_schema": WIKI_SCHEMA,
        },
        "games": {m: _project_for_wiki(rec) for m, rec in out_map.items()}
    }
    ok_out_wiki = _write_json(WIKI_OUT_PATH, wiki_doc)

    # --- Write raw review output (header + games) ---
    raw_doc = {
        "header": {
            "versions": wiki_header_versions,
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "wiki_schema": WIKI_SCHEMA,
        },
        "games": {m: _project_for_raw(m, rec) for m, rec in out_map.items()}
    }
    ok_out_raw = _write_json(RAW_OUT_PATH, raw_doc)

    ok_out = ok_out_wiki and ok_out_raw


    # --- Build and write transform summary ---
    parents_total = sum(1 for v in mame.values() if not v.get("cloneof"))
    clones_total  = sum(1 for v in mame.values() if v.get("cloneof"))


    # ---------------- Wiki pages & redirects (parents only) ----------------
    # Build (page_name, machine) pairs first so we can sort by page title
    pairs: list[tuple[str, str]] = [(_pref(rec.get("wiki_page_name") or ""), machine)
                                    for machine, rec in out_map.items()]

    # Sort by page title (case-insensitive)
    pairs.sort(key=lambda t: t[0].casefold())

    # Reconstruct pages_map in sorted order (machine -> prefixed page)
    pages_map: dict[str, str] = {machine: page for page, machine in pairs}

    # Group by page to build page_names list and detect collisions (do this ONCE)
    page_to_machines: dict[str, list[str]] = {}
    for page, machine in pairs:
        page_to_machines.setdefault(page, []).append(machine)

    # Already sorted by page via 'pairs'; preserve that order
    page_names_list: list[str] = list(page_to_machines.keys())

    # Collisions: same page name claimed by >1 parent
    page_name_collisions: list[dict] = [
        {"page": page, "machines": sorted(machines)}
        for page, machines in page_to_machines.items()
        if len(machines) > 1
    ]

    # Build redirects (from parent parsed titles only; no clones)
    # Case-insensitive de-duplication on sources; record conflicts if the same source maps to different targets
    redirects_map: dict[str, str] = {}
    redirect_conflicts: list[dict] = []
    sources_seen: dict[str, str] = {}  # lower(source) -> target

    for machine, rec in out_map.items():
        target = pages_map[machine]  # prefixed page name
        desc   = rec.get("description") or {}
        wiki_name = rec.get("wiki_page_name") or ""
        for src in _build_redirect_sources(desc, wiki_name):
            psrc = _pref(src)
            key = psrc.casefold()
            prev = sources_seen.get(key)
            if prev is None:
                sources_seen[key] = target
                redirects_map[psrc] = target
            elif prev != target:
                owners = [m for m, p in pages_map.items() if p in {prev, target}]
                redirect_conflicts.append({
                    "source": psrc,
                    "targets": sorted({prev, target}),
                    "machines": sorted(set(owners)),
                })

    # Optional: sort redirects for stability BEFORE embedding
    redirects_map = dict(sorted(redirects_map.items(), key=lambda kv: kv[0].casefold()))

    # Assemble and write file (stats near the top)
    wiki_pages_redirects = {
        "schema_version": 1,
        "prefix": WIKI_PREFIX,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "stats": {
            "parents_total": len(out_map),
            "page_names_total": len(page_names_list),
            "redirects_total": len(redirects_map),
            "page_name_collisions": len(page_name_collisions),
            "redirect_conflicts": len(redirect_conflicts),
        },
        "pages": pages_map,              # machine -> page (sorted by page)
        "page_names": page_names_list,   # sorted list of pages
        "redirects": redirects_map,      # source -> target (both prefixed)
        "conflicts": {
            "page_name_collisions": page_name_collisions,
            "redirect_conflicts": redirect_conflicts,
        },
    }

    _write_json(WIKI_PAGES_REDIRECTS_PATH, wiki_pages_redirects)


    finished_utc = datetime.datetime.utcnow().isoformat() + "Z"
    duration = round(time.perf_counter() - t0, 3)

    # Inputs (artefacts the transformer READ)
    inputs_map = {
        "mame_machines":       str(MAME_MACHINES_PATH).replace("\\", "/"),
        "ini_classifications": str(INI_CLASS_PATH).replace("\\", "/"),
        "mame_parent_index":   str(PARENT_INDEX_PATH).replace("\\", "/"),
    }
    if have_overrides:
        inputs_map["title_overrides"] = str(overrides_path).replace("\\", "/")

    # Outputs (artefacts the transformer WROTE)
    outputs_map = {
        "exotica_lit_wiki":         str(WIKI_OUT_PATH).replace("\\", "/"),
        "exotica_lit_raw_data":     str(RAW_OUT_PATH).replace("\\", "/"),   # NEW
        "wiki_pages_and_redirects": str(WIKI_PAGES_REDIRECTS_PATH).replace("\\", "/"),
    }
    
    #parents_with_clones = sum(1 for r in out_map.values() if r["clones"])
    parents_with_clones = sum(
        1 for r in out_map.values()
        if any(t.get("role") == "clone" for t in r.get("mame_titles", []))
    )
    
    #total_clones_linked = sum(len(r["clones"]) for r in out_map.values())
    total_clones_linked = sum(
        sum(1 for t in r.get("mame_titles", []) if t.get("role") == "clone")
        for r in out_map.values()
    )
        
    # De-dupe anomalies (prefer pre_override entries) and count
    title_anomalies = _dedupe_anomalies_preferring_pre_override(title_anomalies)
    title_anomaly_counts = {k: len(v) for k, v in title_anomalies.items()}

    # Sort media labels for stability (already present)
    media_label_counts_sorted = dict(sorted(media_label_counts.items(), key=lambda kv: kv[0].casefold()))

    # Top-N ignored raw device strings by frequency (desc), then name (asc)
    ignored_sorted = sorted(ignored_device_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ignored_top = [{"device": k, "count": v} for k, v in ignored_sorted[:_IGNORED_TOP_N]]
    ignored_total = sum(ignored_device_counts.values())

    # Build the set of machines included in the export (parents + their clones)
    included_parents_set = set(out_map.keys())
    included_clones_set: set[str] = set()
    for p in included_parents_set:
        for c in (parents_map.get(p) or []):
            included_clones_set.add(c)

    included_all = included_parents_set | included_clones_set

    # GH arcade entries with ports that are NOT in our Arcade/Game export
    # (i.e., excluded by INI scope or by our ports gate)
    gh_not_in_arcade_scope = sorted(gh_keys_with_ports - included_all)


    # Build the clarified 'ports' block for the summary
    summary_ports = {
        # Universe from GH History XML (arcade side)
        "gh_arcade_entries_total": len(gh_ports),
        "gh_arcade_entries_with_ports_total": len(gh_keys_with_ports),

        # Our final export after INI scope + ports gate
        "included_parents_after_ports_gate": len(out_map),

        # Of the included parents, how many have ports on their own GH key
        "included_parents_with_own_ports": {
            "count": parents_with_ports_count,
            "note": "Included parents whose own GH shortname has ≥1 valid port row.",
        },

        # Distinct clones (under included parents) that have ports; full list for traceability
        "included_clones_with_ports": {
            "count": len(clones_with_ports_set),
            "list": sorted(clones_with_ports_set),
            "note": "Clone shortnames (children of included parents) with ≥1 valid GH port row.",
        },

        # GH arcade entries that have ports but are absent from our export (INI scope/filter)
        "gh_arcade_entries_with_ports_excluded_by_ini": {
            "count": len(gh_not_in_arcade_scope),
            "list": gh_not_in_arcade_scope,
            "note": "GH/MAME shortnames with ≥1 valid port row that are not in our Arcade/Game export.",
        },
    }

    # Derived figures (informational)
    parents_included_due_to_clones_only = (
        len(out_map) - parents_with_ports_count
    )


    # --- Parents included due to clone ports only: full list ---
    # A parent is in this bucket if it is included,
    # AND it has NO parent_source in its ports object (i.e., only clones had ports).
    parents_included_due_to_clones_only_list = sorted(
        m for m, rec in out_map.items()
        if not ((rec.get("ports") or {}).get("parent_source"))
    )

    # Optional soft check: length should match the derived count you computed earlier
    if len(parents_included_due_to_clones_only_list) != (
        len(out_map) - parents_with_ports_count
    ):
        log.warning(
            "[ports] parents_included_due_to_clones_only length mismatch: "
            f"list={len(parents_included_due_to_clones_only_list)} "
            f"vs derived={len(out_map) - parents_with_ports_count}"
        )


    summary_ports.setdefault("derived", {})
    summary_ports["derived"].update({
        "parents_included_due_to_clones_only": len(parents_included_due_to_clones_only_list),
        "parents_included_due_to_clones_only_list": parents_included_due_to_clones_only_list,
        "note_parents_included_due_to_clones_only": (
            "Included parents that do not have ports on their own GH key, "
            "but were included because at least one clone has ports."
        ),
    })


    summary = {
        "transformer_schema": TRANSFORMER_SCHEMA,
        "started_utc": started_utc,
        "finished_utc": finished_utc,
        "duration_seconds": duration,
        "inputs": inputs_map,
        "outputs": outputs_map,
        "versions": versions,
        "counts": {
            "mame_total": len(mame),
            "parents_total": parents_total,
            "clones_total": clones_total,
            "eligible_parents": len(eligible_parents),
            "final_included": len(out_map),
            "parents_with_clones": parents_with_clones,
            "total_clones_linked": total_clones_linked,
            "parents_without_clones": len(eligible_parents)-parents_with_clones,
            "parents_with_any_media": parents_with_any_media,
            "media_label_counts": media_label_counts_sorted,
            "audio": {
                "machines_reporting_channels": audio_total_with_channels,
                "channel_speaker_mismatches": audio_channel_speaker_mismatch,
                "mismatch_examples": audio_mismatch_examples,   # up to 10
                "machines_requiring_samples": audio_samples_required_count
            },
        },
        "excluded_parents_by_reason": excluded_reasons,
        "included_flags": included_flags,
        "title_anomaly_counts": title_anomaly_counts,
        "title_anomalies": title_anomalies,
        "title_overrides": {
            "stats": overrides_stats,
            "applied": overrides_applied
        },        
        "ports": summary_ports,
        "notes": {
            "ports_attached": False,
             "export_scope": "Parents are exported only if INI says Arcade/Game AND the parent or any clone has ≥1 valid GH port row (platform present).",
            "filter_rules": {
                "game_status_equals": "game",
                "category_must_include": "Arcade",
                "ignore_coin_op_games": True,
                "ignore_type_for_filter": True,
                "ignore_isbios_isdevice_ismechanical_for_filter": True
            },
            "title_parsing": {
                "numbered_fields": True,
                "global_version_is_single_string": True,
                "only_top_level_groups": True,
                "nested_preserved_inside": True
            },
            "clones_list_title_source": "raw MAME 'description' (no overrides)",
            "ignored_media_devices": {
                "total_ignored_entries": ignored_total,          # sum of all unmapped raw entries
                "unique_ignored": len(ignored_device_counts),    # how many distinct raw strings
                "top_ignored": ignored_top,                      # top N offenders
            },                        
        },
        "errors": [] if ok_out and not missing_in_mame else (
            [{"missing_in_mame": missing_in_mame}] if missing_in_mame else []
        ),
    }

    orphans = [k for k, v in out_map.items() if "mame_titles" not in v]
    if orphans:
        log.warning(f"{len(orphans)} parents missing mame_titles (first few: {orphans[:5]})")

    if ignored_top:
        log.info(f"Top ignored media devices: {ignored_top[:5]}")

    # Soft QA checks (warn-only)
    if parents_with_ports_count > len(out_map):
        log.warning(
            "[ports] parents_with_ports_count > included_parents_after_ports_gate "
            f"({parents_with_ports_count} > {len(out_map)}): check counting logic."
        )

    if not clones_with_ports_set.issubset(included_clones_set):
        extras = sorted(clones_with_ports_set - included_clones_set)[:20]
        log.warning(
            "[ports] Some clones_with_ports are not children of included parents "
            f"(showing up to 20): {extras}"
        )

    if len(gh_keys_with_ports) > len(gh_ports):
        log.warning(
            "[ports] gh_keys_with_ports larger than gh_ports keys "
            f"({len(gh_keys_with_ports)} > {len(gh_ports)}): unexpected."
        )

    # Sanity: 'excluded_by_ini' should be a subset of GH keys
    if not set(summary_ports["gh_arcade_entries_with_ports_excluded_by_ini"]["list"]).issubset(set(gh_keys_with_ports)):
        log.warning("[ports] Excluded-by-INI list contains entries not in gh_keys_with_ports.")


    ok_sum = _write_json(TRANS_SUMMARY_PATH, summary)
    log.info(f"Transformer completed in {duration:.2f}s "
             f"(eligible_parents={len(eligible_parents)}, included={len(out_map)})")
    return bool(ok_out and ok_sum)


if __name__ == "__main__":
    ok = run_transformer(DATA_DIR)
    raise SystemExit(0 if ok else 1)
