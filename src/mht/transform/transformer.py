"""
Filename: transformer.py
Version: 1.0.2
Last modified: 2025-09-30
Author: Jason (XtC) Skelly (Open University TM470, 2025)

Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Transforms parsed artefacts into a Wiki-ready dataset in a single step.

Scope:
- Select parent machines where INI says game_status == "game" AND category includes "Arcade".
- Include a parent in the final export only if the parent OR any of its clones has ≥1 valid
  Gaming-History port row (platform present). Clone data is used for ports and titles display,
  but the export is parent-centric.
- Parse titles into numbered fields (titleN / subtitleN / versionN) plus a global_version string.
  Title parsing tolerates nested brackets and reports anomalies for QA.
- Build wiki display blocks for ROM/media, chips/audio, displays and controls.
- Attach cleaned “ports_display” per category (parent+clone rows combined with date sorting).
- Generate a deterministic pages/redirects map for the ExoticA namespace.

Inputs:
- output/mame_machines.json
- output/gh_ini_classifications.json
- output/mame_parent_index.json
- data/history_parsing_summary.json            (for version header)
- data/mame_parsing_summary.json               (for version header)
- data/ini_parsing_summary.json                (for INI version header)
- data/title_overrides.json (optional)

Outputs:
- output/exotica_lit_wiki.json                 (Wiki-ready projection)
- output/exotica_lit_raw_data.json             (Rich, review-oriented projection)
- output/exotica_wiki_pages_and_redirects.json (Deterministic list + redirects map)
- data/transform_summary.json                  (counts, QA diagnostics, and notes)

Returns:
- True on success, False otherwise.

Notes:
- Deterministic ordering is preserved throughout for stable diffs.
- Ports are attached (parent and clone provenance retained for audit).
- See transform_summary.json → "notes" for the exact selection and parsing rules.
This file is part of a student project and is not intended for commercial use.
"""

from pathlib import Path
from typing import Dict, Any, Optional, Set, List, Tuple, Sequence, Iterable
import json
import datetime
import time
import re
from collections import Counter

from mht.utils.config import LOG_LEVEL
from mht.utils.logger import setup_logger, debug_log
from mht.utils.versions import SCHEMA_IDS, schema_version, tool_version, output_schema
from mht.utils.paths import (
    DATA_DIR, OUTPUT_DIR, STAMPS_DIR,
    # summaries
    MAME_SUMMARY, HISTORY_SUMMARY, INI_SUMMARY, TRANSFORM_SUMMARY,
    # intermediates / inputs
    MAME_MACHINES_PATH, PARENT_INDEX_PATH, GH_SYSTEM_PORTS_PATH, INI_CLASS_PATH,
    # finals
    EXOTICA_WIKI, EXOTICA_RAW, EXOTICA_PAGES,
    # helpers
    ensure_dirs,
)

log = setup_logger(log_level=LOG_LEVEL)

# Legacy field to keep for one cycle, but derive from the canonical summary schema now:
TRANSFORMER_SCHEMA = schema_version(SCHEMA_IDS["transform"])  # was "0.8"

# Output dataset schemas (IDs + versions) now from one source of truth:
SCHEMA_ID_WIKI  = output_schema("wiki")["id"]
SCHEMA_VER_WIKI = output_schema("wiki")["version"]

SCHEMA_ID_RAW   = output_schema("raw")["id"]
SCHEMA_VER_RAW  = output_schema("raw")["version"]

SCHEMA_ID_PAGES  = output_schema("pages")["id"]
SCHEMA_VER_PAGES = output_schema("pages")["version"]

WIKI_PREFIX = "Lost In Translation/"

_ALNUM = re.compile(r"[A-Za-z0-9]")
_INFIX_RE = re.compile(r"[A-Za-z0-9]\([^()\[\]]+\)[A-Za-z0-9]")
_VERSION_CORE_RX = re.compile(r"\d+(?:\.\d+)+")

# Display precedence for the media "Plus:" line (higher = earlier).
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

def _dedupe_ci_preserve_order(items: list[str]) -> list[str]:
    out, seen = [], set()
    for s in items or []:
        key = (s or "").casefold()
        if key and key not in seen:
            seen.add(key)
            out.append(s)
    return out

def _primary_redirects_for_unit1(desc_fields: dict, target_page_name: str) -> list[str]:
    t = _collapse_ws((desc_fields.get("title1") or "").strip())
    s = _collapse_ws((desc_fields.get("subtitle1") or "").strip())
    target_ci = (target_page_name or "").casefold()
    out: list[str] = []
    if not t:
        return out
    if s:
        full = _collapse_ws(f"{t}: {s}")
        if full.casefold() != target_ci:
            out.append(full)
        if t.casefold() != target_ci:
            out.append(t)
    else:
        if t.casefold() != target_ci:
            out.append(t)
    return _dedupe_ci_preserve_order(out)

def _clone_primary_redirects(clone_machine: str,
                             mame: Dict[str, Any],
                             target_page_name: str) -> list[str]:
    minfo = mame.get(clone_machine) or {}
    raw = _raw_mame_title(minfo, clone_machine)
    desc_fields, _ = _parse_description(raw)
    return _primary_redirects_for_unit1(desc_fields, target_page_name)

def _gh_ids_from_ports_obj(ports_obj: dict) -> list[int]:
    ids: set[int] = set()
    if not isinstance(ports_obj, dict):
        return []
    p = ports_obj.get("parent_source") or {}
    gid = p.get("gh_id")
    if isinstance(gid, int):
        ids.add(gid)
    for cs in (ports_obj.get("clone_sources") or []):
        gid = (cs or {}).get("gh_id")
        if isinstance(gid, int):
            ids.add(gid)
    return sorted(ids)

def _collect_gh_ids_from_ports(ports_obj: dict) -> list:
    if not isinstance(ports_obj, dict):
        return []
    ids = set()
    p = ports_obj.get("parent_source")
    if isinstance(p, dict):
        gid = p.get("gh_id")
        if gid is not None:
            ids.add(gid)
    for c in (ports_obj.get("clone_sources") or []):
        if not isinstance(c, dict):
            continue
        gid = c.get("gh_id")
        if gid is not None:
            ids.add(gid)
    return sorted(ids, key=lambda x: str(x))

def _render_chips_display(
    chips_raw: dict,
    requires_samples: bool = False,
    sound_channels: int | None = None,
    speaker_count: int | None = None,
) -> dict[str, list[str]]:
    def _rows(section):
        if isinstance(section, dict):
            return section.get("items") or []
        return section or []
    def _norm_rows(rows):
        for r in rows or []:
            if isinstance(r, dict):
                name = (r.get("name") or "").strip()
                clk  = r.get("clock_hz")
            elif isinstance(r, str):
                name = r.strip()
                clk  = None
            else:
                continue
            if name:
                yield {"name": name, "clock_hz": clk}
    def group_and_render(rows: list[dict]) -> list[str]:
        buckets: dict[tuple[str, int | None], int] = {}
        clocks: dict[tuple[str, int | None], float | None] = {}
        for r in rows:
            name = r["name"]
            clk  = r.get("clock_hz")
            bucket = round(float(clk)) if isinstance(clk, (int, float)) else None
            key = (name, bucket)
            buckets[key] = buckets.get(key, 0) + 1
            clocks.setdefault(key, float(clk) if isinstance(clk, (int, float)) else None)
        ordered = sorted(buckets.items(), key=lambda kv: (kv[0][0].casefold(), -(clocks[kv[0]] or -1)))
        lines: list[str] = []
        for (name, _bucket), count in ordered:
            clk_val = clocks[(name, _bucket)]
            if clk_val is not None:
                human = _hz_to_human(clk_val)
                if human:
                    val, unit = human
                    freq = f"{val:.3f} {unit}"
                else:
                    freq = _format_hz_3dp(clk_val) or ""
            else:
                freq = ""
            base = name + (f" @ {freq}" if freq else "")
            lines.append(f"({count}x) {base}" if count > 1 else base)
        return lines
    cpus_src_rows       = _rows((chips_raw or {}).get("cpus"))
    audio_src_rows_all  = _rows((chips_raw or {}).get("audio_chips"))
    cpus_src      = list(_norm_rows(cpus_src_rows))
    audio_src_all = list(_norm_rows(audio_src_rows_all))
    audio_src = [r for r in audio_src_all if r["name"].lower() not in {"speaker", "samples"}]
    out = {
        "cpus": group_and_render(cpus_src),
        "audio_chips": group_and_render(audio_src),
    }
    tail: list[str] = []
    if requires_samples:
        tail.append("Requires additional samples")
    if sound_channels is not None:
        try:
            n = int(sound_channels)
        except Exception:
            n = 0
        tail.append(f"Audio {'Channel' if n == 1 else 'Channels'}: {n}")
    if speaker_count is None:
        speaker_count = sum(1 for r in audio_src_all if r["name"].lower() == "speaker")
    try:
        nsp = int(speaker_count or 0)
    except Exception:
        nsp = 0
    tail.append(f"{'Speaker' if nsp == 1 else 'Speakers'}: {nsp}")
    if tail:
        out["audio_chips"].extend(tail)
    return out

def _render_mame_titles_display(rows: list[dict]) -> list[str]:
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
        if machine:
            parts.append(f"[{role}: {machine}]")
        else:
            parts.append(f"[{role}]")
        out.append(" ".join(parts))
    return out

def _canonical_port_key(row: dict) -> tuple:
    regions = tuple(r.strip() for r in (row.get("regions") or []) if isinstance(r, str))
    platform = (row.get("platform") or "").strip()
    title    = (row.get("title") or "").strip()
    date     = (row.get("date") or "").strip()
    publisher= (row.get("publisher") or "").strip()
    tags     = tuple(t.strip() for t in (row.get("additional_tags") or []) if isinstance(t, str))
    models   = tuple(m.strip() for m in (row.get("model") or []) if isinstance(m, str))
    comment  = (row.get("comment") or "").strip()
    return (regions, platform, title, date, publisher, tags, models, comment)

def _has_parent_clone_duplicate_ports(ports_obj: dict) -> bool:
    if not isinstance(ports_obj, dict):
        return False
    p = (ports_obj.get("parent_source") or {}).get("categories") or {}
    clones = [ (cs or {}).get("categories") or {} for cs in (ports_obj.get("clone_sources") or []) ]
    if not p or not clones:
        return False
    parent_sets: dict[str, set] = {}
    for cat, rows in p.items():
        s = set()
        for r in (rows or []):
            s.add(_canonical_port_key(r))
        if s:
            parent_sets[cat] = s
    if not parent_sets:
        return False
    for cdict in clones:
        for cat, rows in cdict.items():
            if cat not in parent_sets:
                continue
            for r in (rows or []):
                if _canonical_port_key(r) in parent_sets[cat]:
                    return True
    return False

def _date_sort_key(date_str: str, original_index: int) -> tuple[int, int, int, int]:
    s = (date_str or "").strip()
    y, m, d = "0000", "00", "00"
    parts = s.split("-")
    if len(parts) >= 1 and parts[0]:
        y = parts[0].replace("X", "0")
    if len(parts) >= 2 and parts[1]:
        m = parts[1].replace("X", "0")
    if len(parts) >= 3 and parts[2]:
        d = parts[2].replace("X", "0")
    try:
        yi = int(y)
    except ValueError:
        yi = 0
    try:
        mi = int(m)
    except ValueError:
        mi = 0
    try:
        di = int(d)
    except ValueError:
        di = 0
    return (yi, mi, di, original_index)

def _format_models_bracketed(models: list[str] | None) -> str:
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
        return prov

def _render_ports_display(parent_machine: str, ports_obj: dict) -> dict[str, list[str]]:
    if not isinstance(ports_obj, dict):
        return {}
    out: dict[str, list[str]] = {}
    cat_roles: dict[str, set[str]] = {}
    def _scan_source(source: dict, role: str):
        cats = (source or {}).get("categories") or {}
        for cat_key, rows in cats.items():
            if rows:
                cat_roles.setdefault(cat_key, set()).add(role)
    if ports_obj.get("parent_source"):
        _scan_source(ports_obj["parent_source"], "parent")
    for cs in (ports_obj.get("clone_sources") or []):
        _scan_source(cs, "clone")
    combined: dict[str, list[tuple[int, str, dict]]] = {}
    enc_ix = 0
    def _append_source(source: dict, role: str):
        nonlocal enc_ix
        cats = (source or {}).get("categories") or {}
        for cat_key, rows in cats.items():
            bucket = combined.setdefault(cat_key, [])
            for r in (rows or []):
                bucket.append((enc_ix, role, r))
                enc_ix += 1
    if ports_obj.get("parent_source"):
        _append_source(ports_obj["parent_source"], "parent")
    for cs in (ports_obj.get("clone_sources") or []):
        _append_source(cs, "clone")
    for cat_key, triples in combined.items():
        disp_cat = _title_case_words(cat_key)
        bucket = out.setdefault(disp_cat, [])
        mixed = (cat_roles.get(cat_key) == {"parent", "clone"})
        undated = []
        dated   = []
        for enc, role, r in triples:
            date = (r.get("date") or "").strip()
            if date:
                dated.append((enc, role, r, _date_sort_key(date, enc)))
            else:
                undated.append((enc, role, r))
        dated.sort(key=lambda t: t[3])
        ordered = [ (enc, role, r) for (enc, role, r) in undated ] + \
                  [ (enc, role, r) for (enc, role, r, _) in dated ]
        for enc, role, r in ordered:
            is_parent = (role == "parent")
            regions = _format_regions(r.get("regions"))
            platform = (r.get("platform") or "").strip()
            tags = _format_additional_tags(r.get("additional_tags"))
            title = (r.get("title") or "").strip()
            date  = (r.get("date") or "").strip()
            pub   = (r.get("publisher") or "").strip()
            models_in = _format_models_bracketed(r.get("model"))
            machine = (r.get("machine") or "").strip()
            parts: list[str] = []
            parts.append(regions)
            plat_seg = f"{platform}{tags}"
            if title:
                parts.append(plat_seg)
            else:
                parts.append(f"{plat_seg} {models_in}".strip())
            if title:
                safe_title = title.replace('"', '\\"')
                if models_in:
                    parts.append(f"\"{safe_title} {models_in}\"")
                else:
                    parts.append(f"\"{safe_title}\"")
            if date:
                parts.append(f"({date})")
            if pub:
                parts.append(f"by {pub}")
            left = " ".join(p for p in parts if p)
            comment = (r.get("comment") or "").strip()
            if mixed:
                comment = _append_provenance_comment(comment, is_parent_row=is_parent, machine=machine)
            line = f"{left} : {comment}" if comment else left
            bucket.append(line)
    return out

def _read_gh_ports(path: Path) -> dict:
    data = _read_json(path)
    return data if isinstance(data, dict) else {}

def _is_valid_port_row(row: dict) -> bool:
    plat = (row or {}).get("platform")
    return isinstance(plat, str) and plat.strip() != ""

def _norm_regions(regs) -> list[str]:
    if not regs:
        return ["??"]
    out = []
    for r in regs:
        if isinstance(r, str) and r.strip():
            out.append(r.strip())
    return out or ["??"]

def _norm_tags(tags) -> list[str]:
    out = []
    for t in (tags or []):
        if isinstance(t, str) and t.strip():
            out.append(t.strip())
    return out

def _collect_valid_ports_by_category(
    gh_entry: dict, 
    source_machine: str, 
    source_gh_id: int | None = None
) -> dict[str, list[dict]]:
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
                "machine": source_machine,
                "gh_id": source_gh_id,
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
    out = set()
    for key, entry in gh_ports.items():
        cats = _collect_valid_ports_by_category(entry, key, (entry or {}).get("gh_id"))
        if any(cats.values()):
            out.add(key)
    return out

def _build_ports_for_parent(parent: str,
                            parents_map: dict[str, list],
                            gh_ports: dict) -> tuple[dict | None, set[str], bool]:
    ports_obj: dict = {"clone_sources": []}
    clones_with_ports: set[str] = set()
    parent_has_ports = False
    p_entry = gh_ports.get(parent)
    if isinstance(p_entry, dict):
        p_cats = _collect_valid_ports_by_category(p_entry, parent, p_entry.get("gh_id"))
        if any(p_cats.values()):
            ports_obj["parent_source"] = {
                "machine": parent,
                "gh_id": p_entry.get("gh_id"),
                "categories": p_cats,
            }
            parent_has_ports = True
    for clone in (parents_map.get(parent) or []):
        c_entry = gh_ports.get(clone)
        if not isinstance(c_entry, dict):
            continue
        c_cats = _collect_valid_ports_by_category(c_entry, clone, c_entry.get("gh_id"))
        if any(c_cats.values()):
            ports_obj["clone_sources"].append({
                "machine": clone,
                "gh_id": c_entry.get("gh_id"),
                "categories": c_cats,
            })
            clones_with_ports.add(clone)
    if not parent_has_ports and not ports_obj["clone_sources"]:
        return None, clones_with_ports, False
    return ports_obj, clones_with_ports, parent_has_ports

def _control_type_label(raw_type: str | None) -> str:
    t = (raw_type or "").strip().lower()
    return _CONTROL_TYPE_LABELS.get(t, t.title() if t else "Unknown Control")

def _ways_pretty(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if s in {"vertical2", "strange2"}:
        return "2-way"
    m = re.match(r"^(\d+)\s*\(half(\d+)\)$", s)
    if m:
        return f"{m.group(1)}-of-{m.group(2)}-way"
    if s.isdigit():
        return f"{int(s)}-way"
    return raw.strip()

def _ways_label(ways: str | None, ways2: str | None, ways3: str | None) -> str:
    parts = [p for p in map(_ways_pretty, (ways, ways2, ways3)) if p]
    return ", ".join(parts)

def _control_line_from_row(row: dict) -> str:
    typ = _control_type_label(row.get("type"))
    ways = _ways_label(row.get("ways"), row.get("ways2"), row.get("ways3"))
    return f"{ways} {typ}".strip() if ways else typ

def _buttons_count_from_rows(rows: list[dict]) -> int:
    total = 0
    for r in rows:
        try:
            n = int(r.get("buttons")) if r.get("buttons") is not None else 0
        except Exception:
            n = 0
        total += max(0, n)
    return total

def _pluralise(singular: str, n: int, plural: str | None = None) -> str:
    return singular if int(n or 0) == 1 else (plural or f"{singular}s")

def _orientation_from_rotate(rot) -> str | None:
    try:
        r = int(rot)
    except Exception:
        return None
    if r in (0, 180):
        return "Horizontal"
    if r in (90, 270):
        return "Vertical"
    return None

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
    per_player: list[dict] = []
    for p in sorted(bucket.keys()):
        rows = bucket[p]
        raw_lines = [_control_line_from_row(r) for r in rows]
        counts = Counter(l.casefold() for l in raw_lines)
        order = list(dict.fromkeys(raw_lines))
        control_lines = [
            (f"({counts[l.casefold()]}x) {l}" if counts[l.casefold()] > 1 else l)
            for l in order
        ]
        btn_total = _buttons_count_from_rows(rows)
        per_player.append({
            "player": p,
            "control_lines": control_lines,
            "buttons": btn_total
        })
    def _placeholder(p: int) -> dict:
        return {"player": p, "control_lines": ["Unknown controls"], "buttons": 0}
    if not per_player:
        if pcount > 0:
            per_player = [_placeholder(p) for p in range(1, pcount + 1)]
        else:
            return {"players": 0, "per_player": []}
        return {"players": pcount, "per_player": per_player}
    if pcount > 0:
        present = {e["player"] for e in per_player}
        for p in range(1, pcount + 1):
            if p not in present:
                per_player.append(_placeholder(p))
        per_player.sort(key=lambda e: e["player"])
    return {"players": pcount, "per_player": per_player}

def _controls_section_to_display(section: dict) -> str:
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
    disp_list = displays or []
    groups: dict[tuple, int] = {}
    for d in disp_list:
        typ = _type_title(d.get("type"))
        ori = _orientation_from_rotate(d.get("rotate")) or ""
        hz_str = _format_hz_3dp(d.get("refresh_hz"))
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

def _build_chips_section(chips: list[dict] | None,
                         sound_channels: int | None,
                         device_ref):
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
                continue
            audio_chip_labels_raw.append(_chip_label(name_raw, clk))
            continue
    cpu_items = _prefix_multiples(cpu_labels_raw)
    audio_items = _prefix_multiples(audio_chip_labels_raw)
    cpu_heading = _pluralise("CPU", len(cpu_labels_raw))
    audio_heading = _pluralise("Audio Chip", len(audio_chip_labels_raw), "Audio Chips")
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
    nm = (name or "").strip()
    h = _hz_to_human(clock_hz)
    return f"{nm} @ {h[0]:.3f} {h[1]}" if h else nm

def _prefix_multiples(labels: list[str]) -> list[str]:
    labels = [l for l in labels if l]
    counts = Counter(l.casefold() for l in labels)
    first_seen_unique = list(dict.fromkeys(labels))
    out = []
    for lab in first_seen_unique:
        n = counts[lab.casefold()]
        out.append(f"({n}x) {lab}" if n > 1 else lab)
    return out

def _sum_device_speakers(device_ref) -> int:
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
    cpu_labels: list[str] = []
    audio_chip_labels: list[str] = []
    speaker_count = 0
    for ch in (chips or []):
        typ = (ch.get("type") or "").strip().lower()
        name_raw = (ch.get("name") or "").strip()
        clk = ch.get("clock_hz")
        name_ci = name_raw.casefold()
        if typ == "cpu":
            cpu_labels.append(_chip_label(name_raw, clk))
            continue
        if typ == "audio":
            if name_ci == "speaker":
                speaker_count += 1
                continue
            if name_ci in {"samples", "sample"}:
                continue
            audio_chip_labels.append(_chip_label(name_raw, clk))
            continue
    lines: list[str] = []
    if cpu_labels:
        lines.append("CPU: " + ", ".join(_prefix_multiples(cpu_labels)))
    if audio_chip_labels:
        lines.append("Audio: " + ", ".join(_prefix_multiples(audio_chip_labels)))
    if _has_samples_flag(device_ref):
        lines.append("Requires additional samples")
    try:
        chn = int(sound_channels) if sound_channels is not None else 0
    except Exception:
        chn = 0
    if chn > 0:
        lines.append(f"Audio channels: {chn}")
    if speaker_count > 0:
        lines.append(f"({speaker_count}x) Speaker")
    return "\n".join(lines)

def _order_media_labels(labels: list[str]) -> list[str]:
    labels = list(dict.fromkeys(labels))
    return sorted(labels, key=lambda s: (-_MEDIA_ORDER.get(s, -1), s.casefold()))

def _normalise_device_to_media(raw: str) -> str | None:
    s = (raw or "").lower()
    tokens = set(re.findall(r"[a-z0-9_]+", s))
    if (
        "laserdisc" in tokens
        or any(t.startswith("laserdisc") for t in tokens)
        or re.search(r"\b(ld_)?(ldv1000|pr7820|pr8210a?|22vp932)\b", s)
    ):
        return "LaserDisc"
    if "ced_videodisc" in tokens:
        return "Capacitance Electronic Disc (CED)"
    if "gdrom" in tokens:
        return "GD-ROM"
    if {"dvdrom", "dvd"} & tokens or any(t.startswith("dvdrom") for t in tokens):
        return "DVD-ROM"
    if (
        {"cdrom", "cd", "audiocd", "cdxa", "xm3301", "cr589", "stvcd"} & tokens
        or any(t.startswith("cdrom") for t in tokens)
    ):
        return "CD-ROM"
    if {"hdd", "harddisk", "scsi_hdd_image"} & tokens or ":hdd" in s:
        return "Hard disk"
    if {"cf", "cfcard", "cflash", "ataflash", "taitocf", "taitopccard1", "taitopccard2", "pccard"} & tokens:
        return "CompactFlash card"
    if {"sdcard", "internalsd"} & tokens:
        return "Secure Digital card"
    if "nand" in tokens:
        return "NAND flash"
    if "usb" in tokens:
        return "USB storage"
    if "vhs" in tokens:
        return "VHS tape"
    return None

def _normalise_device_list_to_media(devs: Iterable[str] | str | None) -> list[str]:
    if devs is None:
        return []
    seq = devs if isinstance(devs, (list, tuple)) else [devs]
    out: list[str] = []
    seen: set[str] = set()
    for raw in seq:
        label = _normalise_device_to_media(str(raw))
        if not label:
            continue
        key = label.casefold()
        if key not in seen:
            seen.add(key)
            out.append(label)
    return out

def join_with_ampersand(items: Sequence[str]) -> str:
    n = len(items)
    if n == 0:
        return ""
    if n == 1:
        return items[0]
    if n == 2:
        return f"{items[0]} & {items[1]}"
    return f"{', '.join(items[:-1])} & {items[-1]}"

def _split_outside_parens(s: str) -> list[str]:
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
    return parts

def _format_rom_block(rom_count: int,
                      rom_bytes_total: int,
                      disk_required: str | None,
                      disk_regions) -> str:
    line1 = f"{rom_count:,} ROM" + ("" if rom_count == 1 else "s")
    total_bytes = int(rom_bytes_total or 0)
    human = _bytes_to_binary_human(total_bytes)
    line2 = f"{total_bytes:,} bytes" + (f" ({human[0]:.2f} {human[1]})" if human else "")
    line3 = None
    if (disk_required or "").lower() == "yes":
        seq = disk_regions if isinstance(disk_regions, (list, tuple)) else ([disk_regions] if disk_regions else [])
        all_labels: list[str] = []
        for raw in seq:
            lab = _normalise_device_to_media(str(raw))
            if lab:
                all_labels.append(lab)
        if all_labels:
            counts = Counter(l.casefold() for l in all_labels)
            first_seen_unique = list(dict.fromkeys(all_labels))
            ordered_unique = _order_media_labels(first_seen_unique)
            display_labels = []
            for lab in ordered_unique:
                n = counts[lab.casefold()]
                display_labels.append(f"({n}x) {lab}" if n > 1 else lab)
            line3 = f"Plus: {join_with_ampersand(display_labels)}"
    return "\n".join([line1, line2] + ([line3] if line3 else []))

def _bytes_to_binary_human(n: int) -> tuple[float, str] | None:
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
    return " ".join((s or "").split())

def _pref(name: str, prefix: str = WIKI_PREFIX) -> str:
    return f"{prefix}{name}"

def _unit_count_from_desc(desc_fields: dict) -> int:
    nums = []
    for k in desc_fields.keys():
        if k.startswith("title") and k[5:].isdigit():
            nums.append(int(k[5:]))
    return max(nums) if nums else 1

def _build_redirect_sources(desc_fields: dict, wiki_page_name: str) -> list[str]:
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
    for i in range(2, n_units + 1):
        ti = (desc_fields.get(f"title{i}") or "").strip()
        si = (desc_fields.get(f"subtitle{i}") or "").strip()
        if ti:
            add(ti)
            if si:
                add(f"{ti}: {si}")
    t1 = (desc_fields.get("title1") or "").strip()
    s1 = (desc_fields.get("subtitle1") or "").strip()
    if t1 and s1:
        add(t1)
    return sources

def _raw_mame_title(minfo: dict, fallback: str) -> str:
    return (minfo.get("description")
            or minfo.get("title")
            or minfo.get("fullname")
            or fallback)

def _mame_titles_for_parent(parent_name: str,
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

def _wiki_page_name_from_desc(desc_fields: dict) -> str:
    title = (desc_fields.get("title1") or "").strip()
    subtitle = (desc_fields.get("subtitle1") or "").strip()
    return f"{title}: {subtitle}" if subtitle else title

def _clone_entries_for_parent(parent_name: str,
                              mame: Dict[str, Any],
                              parent_index: Dict[str, Any]) -> list[dict]:
    clones = (parent_index.get("parents") or {}).get(parent_name, []) or []
    out: list[dict] = []
    for c in sorted(clones):
        minfo = mame.get(c, {})
        out.append({
            "machine": c,
            "title": _raw_mame_title(minfo, c),
            "year": minfo.get("year"),
        })
    return out

def _core(s: str | None) -> str | None:
    if not s:
        return None
    m = _VERSION_CORE_RX.search(s)
    return m.group(0) if m else None

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
    out = {}
    if rec.get("wiki_page_name"): out["wiki_page_name"] = rec["wiki_page_name"]
    out["wiki_redirects"] = rec.get("wiki_redirects", [])
    if rec.get("year") is not None: out["year"] = rec["year"]
    if rec.get("manufacturer") is not None: out["manufacturer"] = rec["manufacturer"]
    if rec.get("mame_titles_display"):
        out["mame_titles_display"] = rec["mame_titles_display"]
    for k in ("roms_display", "chips_display", "displays_display", "controls_display"):
        if rec.get(k): out[k] = rec[k]
    if rec.get("ports_display"):
        out["ports_display"] = rec["ports_display"]
    if rec.get("gh_ids"):
        out["gh_ids"] = rec["gh_ids"]
    return out

def _project_for_raw(machine: str, rec: dict) -> dict:
    out = {}
    out["machine"] = machine
    if rec.get("wiki_page_name"): out["wiki_page_name"] = rec["wiki_page_name"]
    out["wiki_redirects"] = rec.get("wiki_redirects", [])
    if rec.get("mame_titles"): out["mame_titles"] = rec["mame_titles"]
    if rec.get("description"): out["description"] = rec["description"]
    if rec.get("year") is not None: out["year"] = rec["year"]
    if rec.get("manufacturer") is not None: out["manufacturer"] = rec["manufacturer"]
    for k in ("rom_count", "rom_bytes_total", "disk_required", "disk_regions"):
        if k in rec: out[k] = rec[k]
    if rec.get("chips"): out["chips"] = rec["chips"]
    if rec.get("displays"): out["displays"] = rec["displays"]
    if rec.get("controls"): out["controls"] = rec["controls"]
    if rec.get("ports"): out["ports"] = rec["ports"]
    for k in ("game_status", "category", "type", "isbios", "isdevice", "ismechanical", "requires_samples"):
        if k in rec: out[k] = rec[k]
    if rec.get("gh_ids"): out["gh_ids"] = rec["gh_ids"]
    return out

def _classify(machine: str, ini_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
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
    info = mame.get(machine, {})
    if info.get("cloneof"):
        return False
    c = _classify(machine, ini_map)
    return (c["game_status"] == "game") and ("Arcade" in c["category"])

def _build_final_set(eligible_parents: Set[str],
                     parent_index: Dict[str, Any]) -> Set[str]:
    final: Set[str] = set(eligible_parents)
    parents_map: Dict[str, list] = (parent_index or {}).get("parents", {})
    for p in sorted(eligible_parents):
        final.update(parents_map.get(p, []))
    return final

def _machine_title(m: Dict[str, Any], fallback: str) -> str:
    return m.get("description") or m.get("title") or m.get("fullname") or fallback

def _truthy_flag(v) -> bool:
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

def _normalise_inside_group(s: str) -> Tuple[str, bool]:
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
    groups = []
    dR = dS = 0
    i = 0
    while i < len(unit):
        ch = unit[i]
        if ch in "([":
            if dR == 0 and dS == 0:
                start = i
                btype = ch
                i += 1
                dR += (ch == "(")
                dS += (ch == "[")
                while i < len(unit) and (dR > 0 or dS > 0):
                    if unit[i] == "(": dR += 1
                    elif unit[i] == ")": dR -= 1
                    elif unit[i] == "[": dS += 1
                    elif unit[i] == "]": dS -= 1
                    i += 1
                end = i - 1
                raw = unit[start+1:end]
                content, _ = _normalise_inside_group(raw)
                groups.append((start, end, "(" if btype == "(" else "[", content))
                continue
        i += 1
    return groups

def _first_trailing_start(unit: str, groups: List[Tuple[int,int,str,str]]) -> Optional[int]:
    for (start, end, _, _) in groups:
        if start == 0:
            return start
        prev = unit[start - 1]
        if prev.isspace():
            return start
    return None

def _split_outside_tokens_after(unit: str, groups: List[Tuple[int,int,str,str]], from_index: int) -> List[str]:
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
    t = t.strip()
    while t and t[0] in "-:,/;()[]":
        t = t[1:].lstrip()
    while t and t[-1] in "-:,/;()[]":
        t = t[:-1].rstrip()
    t = " ".join(t.split())
    return t

def _find_infix_brackets_no_spaces(s: str) -> bool:
    return _INFIX_RE.search(s) is not None

def _find_unbalanced(full: str) -> Tuple[bool, bool]:
    dR = dS = 0
    for ch in full:
        if ch == "(": dR += 1
        elif ch == ")": dR -= 1
        elif ch == "[": dS += 1
        elif ch == "]": dS -= 1
    return (dR != 0, dS != 0)

def _parse_unit(unit_text: str) -> Tuple[str, str, List[str], List[str], Dict[str, bool]]:
    warn = {"odd_separator_usage": False}
    groups = _top_level_groups(unit_text)
    first_tr_start = _first_trailing_start(unit_text, groups)
    cut = first_tr_start if first_tr_start is not None else len(unit_text)
    head = unit_text[:cut]
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
    anomalies: Dict[str, List[Dict[str, str]]] = {
        "unbalanced_round_brackets": [],
        "unbalanced_square_brackets": [],
        "infix_brackets_no_spaces": [],
        "ambiguous_trailing_tokens": [],
        "odd_separator_usage": [],
    }
    unb_round, unb_square = _find_unbalanced(full_desc)
    if unb_round:  anomalies["unbalanced_round_brackets"].append({"example": full_desc})
    if unb_square: anomalies["unbalanced_square_brackets"].append({"example": full_desc})
    if _find_infix_brackets_no_spaces(full_desc):
        anomalies["infix_brackets_no_spaces"].append({"example": full_desc})
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
    desc: Dict[str, str] = {}
    for idx in range(len(unit_info)):
        desc[f"title{idx+1}"] = ""
        desc[f"subtitle{idx+1}"] = ""
        desc[f"version{idx+1}"] = ""
    for idx, (base, sub, _, _, _) in enumerate(unit_info, start=1):
        desc[f"title{idx}"] = base
        desc[f"subtitle{idx}"] = sub
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

def run_transformer(data_dir: Path = DATA_DIR) -> bool:
    started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    t0 = time.perf_counter()

    # --- Stage stamp: skip unchanged (using centralised stamp path) ---
    STAMPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp_path = STAMPS_DIR / "transform.json"

    stamp_inputs = [
        MAME_MACHINES_PATH,
        INI_CLASS_PATH,
        PARENT_INDEX_PATH,
        GH_SYSTEM_PORTS_PATH,
        DATA_DIR / "mame_parsing_summary.json",
        DATA_DIR / "history_parsing_summary.json",
        DATA_DIR / "ini_parsing_summary.json",
        DATA_DIR / "title_overrides.json",
    ]

    current_stamp = make_stamp(
        schema_id="mht.stage.transform",
        tool_version=tool_version("transformer"),
        inputs=stamp_inputs,
        #extra={"selection_rules": "v1", "title_parser": "v1"},
    )

    prev = load_stamp(stamp_path)
    if is_fresh(current_stamp, prev):
        log.info("Transform stage up-to-date (stamp matched) — skipping transform")
        return True

    wiki_header_versions = {
        "mame_xml_version": "Unknown",
        "gaming_history_xml_version": "Unknown",
        "ini_versions": {}
    }

    overrides_path = DATA_DIR / "title_overrides.json"
    overrides = _load_title_overrides(overrides_path)
    have_overrides = isinstance(overrides, dict) and bool(overrides)
    overrides_applied: list[dict[str, str]] = []
    overrides_stats = {"configured": len(overrides), "eligible": 0, "applied": 0}

    mame = _read_json(MAME_MACHINES_PATH)
    ini_map = _read_json(INI_CLASS_PATH)
    parent_index = _read_json(PARENT_INDEX_PATH)
    gh_ports = _read_gh_ports(GH_SYSTEM_PORTS_PATH)
    gh_keys_with_ports = _gh_keys_with_any_valid_ports(gh_ports)

    if not isinstance(mame, dict) or not isinstance(ini_map, dict) or not isinstance(parent_index, dict):
        log.error("Missing or invalid inputs; aborting transform.")
        return False

    parents_map: Dict[str, list] = (parent_index or {}).get("parents", {})

    mame_sum = _read_json(MAME_SUMMARY) or {}
    hist_sum = _read_json(HISTORY_SUMMARY) or {}
    ini_sum  = _read_json(INI_SUMMARY) or {}

    def _get(d, *path, default=None):
        cur = d
        for k in path:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    mame_build_val       = _get(mame_sum, "header", "versions", "mame_build")       or _get(mame_sum, "mame", "build")
    history_version_val  = _get(hist_sum, "header", "versions", "gh_version")       or _get(hist_sum, "history", "version")
    history_date_val     = _get(hist_sum, "header", "versions", "gh_date")          or _get(hist_sum, "history", "date")
    ini_generated_at_val = _get(ini_sum,  "header", "generated_at")                  or _get(ini_sum,  "ini", "generated_at")

    versions = {
        "mame_build":       mame_build_val,
        "history_version":  history_version_val,
        "history_date":     history_date_val,
        "ini_generated_at": ini_generated_at_val,
    }

    mame_build_raw   = mame_build_val
    mame_core        = _core(mame_build_raw) or _get(mame_sum, "header", "versions", "mame_xml_version")
    hist_version_raw = history_version_val

    ini_versions_raw: dict[str, str] = {}
    ini_root = (ini_sum.get("ini") or {}) if isinstance(ini_sum, dict) else {}
    files_node = ini_root.get("files")
    if isinstance(files_node, dict):
        for item in files_node.values():
            fn = (item.get("filename") or item.get("path") or "").strip()
            v  = item.get("version") or {}
            ver = v.get("mame_version") or v.get("raw") or "Unknown"
            if fn:
                ini_versions_raw[fn] = ver
    if not ini_versions_raw:
        files_list = ini_sum.get("files")
        if isinstance(files_list, list):
            for item in files_list:
                fn = (item.get("filename") or item.get("path") or "").strip()
                v  = item.get("version") or {}
                ver = v.get("mame_version") or v.get("raw") or "Unknown"
                if fn:
                    ini_versions_raw[fn] = ver
    if not ini_versions_raw:
        for item in (ini_root.get("inputs") or ini_sum.get("inputs") or []):
            fn = (item.get("filename") or item.get("path") or "").strip()
            v  = item.get("version") or {}
            ver = v.get("mame_version") or v.get("raw") or "Unknown"
            if fn:
                ini_versions_raw[fn] = ver

    wiki_header_versions = {
        "mame_xml_version":            mame_core or "Unknown",
        "gaming_history_xml_version":  hist_version_raw or "Unknown",
        "ini_versions":                {fn: (ini_versions_raw.get(fn) or "Unknown") for fn in ini_versions_raw}
    }

    all_names = sorted(mame.keys())
    eligible_parents: Set[str] = {n for n in all_names if _is_eligible_parent(n, mame, ini_map)}
    included_parents: Set[str] = eligible_parents

    out_map: Dict[str, Dict[str, Any]] = {}
    excluded_reasons = {"not_game": 0, "not_arcade": 0, "unknown_classification": 0}
    included_flags = {"isbios": 0, "isdevice": 0, "ismechanical": 0}
    missing_in_mame: List[str] = []
    systems_with_parent_clone_port_dupes = 0
    systems_with_parent_clone_port_dupes_list: list[str] = []
    title_anomalies: Dict[str, List[Dict[str, str]]] = {
        "unbalanced_round_brackets": [],
        "unbalanced_square_brackets": [],
        "infix_brackets_no_spaces": [],
        "ambiguous_trailing_tokens": [],
        "odd_separator_usage": [],
    }
    media_label_counts: dict[str, int] = {}
    parents_with_any_media = 0
    ignored_device_counts: dict[str, int] = {}
    _IGNORED_TOP_N = 25
    audio_total_with_channels = 0
    audio_channel_speaker_mismatch = 0
    audio_mismatch_examples: list[dict] = []
    audio_samples_required_count = 0
    parents_with_ports_count = 0
    clones_with_ports_set: set[str] = set()

    for name in sorted(included_parents):
        minfo = mame.get(name)
        if not minfo:
            continue
        cls = _classify(name, ini_map)
        raw_desc_original = _machine_title(minfo, name)
        _, pre_anoms = _parse_description(raw_desc_original)
        for k, lst in pre_anoms.items():
            for item in lst:
                item["machine"] = name
                item["pre_override"] = True
            title_anomalies[k].extend(lst)
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
        desc_fields, _ = _parse_description(raw_desc)
        wiki_page_name = _wiki_page_name_from_desc(desc_fields)
        raw_man = minfo.get("manufacturer") or ""
        manufacturer_display = join_with_ampersand(_split_outside_parens(raw_man))
        rom_count       = int(minfo.get("rom_count") or 0)
        rom_bytes_total = int(minfo.get("rom_bytes_total") or 0)
        disk_required = minfo.get("disk_required")
        disk_regions  = minfo.get("disk_regions")
        roms_display = _format_rom_block(rom_count, rom_bytes_total, disk_required, disk_regions)
        if (str(disk_required or "").lower() == "yes"):
            labels_for_counts = _normalise_device_list_to_media(disk_regions)
            if labels_for_counts:
                parents_with_any_media += 1
                for lab in dict.fromkeys(labels_for_counts):
                    media_label_counts[lab] = media_label_counts.get(lab, 0) + 1
            seq = disk_regions if isinstance(disk_regions, (list, tuple)) else ([disk_regions] if disk_regions else [])
            for raw in seq:
                if _normalise_device_to_media(str(raw)) is None:
                    ignored_device_counts[str(raw)] = ignored_device_counts.get(str(raw), 0) + 1
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
        try:
            chn = int(reported_channels) if reported_channels is not None else 0
        except Exception:
            chn = 0
        if chn > 0:
            audio_total_with_channels += 1
            if speaker_sum != chn:
                audio_channel_speaker_mismatch += 1
                if len(audio_mismatch_examples) < 10:
                    audio_mismatch_examples.append({
                        "machine": name,
                        "sound_channels": chn,
                        "speaker_sum": speaker_sum
                    })
        if _has_samples_flag(minfo.get("device_ref")):
            audio_samples_required_count += 1
        chips_disp = _render_chips_display(
            chips_section,
            requires_samples=_truthy_flag(minfo.get("requires_samples")),
            sound_channels=(int(reported_channels) if reported_channels not in (None, "") else None),
            speaker_count=(int(speaker_sum) if speaker_sum not in (None, "") else None),
        )
        cpus_lines = list(chips_disp.get("cpus") or [])
        audio_lines = list(chips_disp.get("audio_chips") or [])
        cpu_hdr   = f"{_pluralise('CPU', len(cpus_lines), 'CPUs')}:"
        audio_hdr = f"{_pluralise('Audio Chip', len(audio_lines), 'Audio Chips')}:"
        chips_display_block = "\n".join([cpu_hdr, *cpus_lines, audio_hdr, *audio_lines])
        ports_obj, clones_with_ports_local, parent_has_ports = _build_ports_for_parent(
            name, parents_map, gh_ports
        )
        if ports_obj is None:
            continue
        if not isinstance(ports_obj.get("clone_sources"), list):
            ports_obj["clone_sources"] = []
        if not isinstance(ports_obj.get("parent_source"), dict):
            ports_obj["parent_source"] = {}
        clones_with_ports_set.update(clones_with_ports_local)
        if parent_has_ports:
            parents_with_ports_count += 1
        if _has_parent_clone_duplicate_ports(ports_obj):
            systems_with_parent_clone_port_dupes += 1
            systems_with_parent_clone_port_dupes_list.append(name)
        gh_ids = _gh_ids_from_ports_obj(ports_obj)
        record = {
            "wiki_page_name": wiki_page_name,
            "description": desc_fields,
            "year": minfo.get("year") if minfo.get("year") not in ("", None) else None,
            "manufacturer": manufacturer_display if manufacturer_display else None,
            "roms_display": roms_display,
            "rom_count": rom_count,
            "rom_bytes_total": rom_bytes_total,
            "disk_required": disk_required,
            "disk_regions": disk_regions,
            "chips": chips_section,
            "chips_display": chips_display_block,
            "displays": displays_section,
            "displays_display": displays_display,
            "controls": controls_section,
            "controls_display": controls_display,
            "game_status": cls["game_status"],
            "category": cls["category"],
            "type": cls["type"],
            "isbios": _truthy_flag(minfo.get("isbios")),
            "isdevice": _truthy_flag(minfo.get("isdevice")),
            "ismechanical": _truthy_flag(minfo.get("ismechanical")),
            "requires_samples": _truthy_flag(minfo.get("requires_samples")),
            "mame_titles": _mame_titles_for_parent(name, mame, parent_index),
            "ports": ports_obj,
            "gh_ids": gh_ids,
        }
        mt_disp = _render_mame_titles_display(record["mame_titles"])
        if mt_disp:
            record["mame_titles_display"] = mt_disp
        parent_redirects = _build_redirect_sources(desc_fields, wiki_page_name)
        clone_redirects: list[str] = []
        for cs in (ports_obj.get("clone_sources") or []):
            c_machine = (cs or {}).get("machine")
            if not c_machine:
                continue
            clone_redirects.extend(_clone_primary_redirects(c_machine, mame, wiki_page_name))
        merged_redirects: list[str] = []
        target_ci = (wiki_page_name or "").casefold()
        for s in (parent_redirects + clone_redirects):
            n = _collapse_ws(s)
            if n and n.casefold() != target_ci:
                merged_redirects.append(n)
        record["wiki_redirects"] = _dedupe_ci_preserve_order(merged_redirects)
        ports_display = _render_ports_display(name, ports_obj)
        if ports_display:
            record["ports_display"] = ports_display
        if _truthy_flag(minfo.get("isbios")):       included_flags["isbios"] += 1
        if _truthy_flag(minfo.get("isdevice")):     included_flags["isdevice"] += 1
        if _truthy_flag(minfo.get("ismechanical")): included_flags["ismechanical"] += 1
        out_map[name] = record

    wiki_doc = {
        "header": {
            "schema_id": SCHEMA_ID_WIKI,
            "schema_version": SCHEMA_VER_WIKI,
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "versions": wiki_header_versions,
        },
        "games": {m: _project_for_wiki(rec) for m, rec in out_map.items()}
    }
    ok_out_wiki = _write_json(EXOTICA_WIKI, wiki_doc)

    raw_doc = {
        "header": {
            "schema_id": SCHEMA_ID_RAW,
            "schema_version": SCHEMA_VER_RAW,
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "versions": wiki_header_versions,
        },
        "games": {m: _project_for_raw(m, rec) for m, rec in out_map.items()}
    }
    ok_out_raw  = _write_json(EXOTICA_RAW,  raw_doc)
    
    ok_out = ok_out_wiki and ok_out_raw

    parents_total = sum(1 for v in mame.values() if not v.get("cloneof"))
    clones_total  = sum(1 for v in mame.values() if v.get("cloneof"))

    pairs: list[tuple[str, str]] = [(_pref(rec.get("wiki_page_name") or ""), machine)
                                    for machine, rec in out_map.items()]
    pairs.sort(key=lambda t: t[0].casefold())
    pages_map: dict[str, str] = {machine: page for page, machine in pairs}
    page_to_machines: dict[str, list[str]] = {}
    for page, machine in pairs:
        page_to_machines.setdefault(page, []).append(machine)
    page_names_list: list[str] = list(page_to_machines.keys())
    page_name_collisions: list[dict] = [
        {"page": page, "machines": sorted(machines)}
        for page, machines in page_to_machines.items()
        if len(machines) > 1
    ]
    redirects_map: dict[str, str] = {}
    redirect_conflicts: list[dict] = []
    sources_seen: dict[str, str] = {}
    for machine, rec in out_map.items():
        target = pages_map[machine]
        wiki_name = rec.get("wiki_page_name") or ""
        sources = rec.get("wiki_redirects")
        if not sources:
            desc = rec.get("description") or {}
            sources = _build_redirect_sources(desc, wiki_name)
        for src in (sources or []):
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
    pages_map_sorted     = dict(sorted(pages_map.items(), key=lambda kv: kv[0].casefold()))
    redirects_map_sorted = dict(sorted(redirects_map.items(), key=lambda kv: kv[0].casefold()))
    page_names_list_sorted = sorted(page_names_list, key=str.casefold)
    generated_at_iso = datetime.datetime.utcnow().isoformat() + "Z"
    wiki_pages_redirects = {
        "header": {
            "schema_id": SCHEMA_ID_PAGES,
            "schema_version": SCHEMA_VER_PAGES,
            "generated_at": generated_at_iso,
        },
        "prefix": WIKI_PREFIX,
        "stats": {
            "parents_total": len(out_map),
            "page_names_total": len(page_names_list_sorted),
            "redirects_total": len(redirects_map_sorted),
            "page_name_collisions": len(page_name_collisions),
            "redirect_conflicts": len(redirect_conflicts),
        },
        "pages": pages_map_sorted,
        "page_names": page_names_list_sorted,
        "redirects": redirects_map_sorted,
        "conflicts": {
            "page_name_collisions": page_name_collisions,
            "redirect_conflicts": redirect_conflicts,
        },
    }
    _write_json(EXOTICA_PAGES, wiki_pages_redirects)

    finished_utc = datetime.datetime.utcnow().isoformat() + "Z"
    duration = round(time.perf_counter() - t0, 3)

    inputs_map = {
        "mame_machines":       str(MAME_MACHINES_PATH).replace("\\", "/"),
        "ini_classifications": str(INI_CLASS_PATH).replace("\\", "/"),
        "mame_parent_index":   str(PARENT_INDEX_PATH).replace("\\", "/"),
    }
    if have_overrides:
        inputs_map["title_overrides"] = str(overrides_path).replace("\\", "/")

    outputs_map = {
        "exotica_lit_wiki":         str(EXOTICA_WIKI).replace("\\", "/"),
        "exotica_lit_raw_data":     str(EXOTICA_RAW).replace("\\", "/"),
        "wiki_pages_and_redirects": str(EXOTICA_PAGES).replace("\\", "/"),
    }

    parents_with_clones = sum(
        1 for r in out_map.values()
        if any(t.get("role") == "clone" for t in r.get("mame_titles", []))
    )
    total_clones_linked = sum(
        sum(1 for t in r.get("mame_titles", []) if t.get("role") == "clone")
        for r in out_map.values()
    )

    title_anomalies = _dedupe_anomalies_preferring_pre_override(title_anomalies)
    title_anomaly_counts = {k: len(v) for k, v in title_anomalies.items()}
    media_label_counts_sorted = dict(sorted(media_label_counts.items(), key=lambda kv: kv[0].casefold()))
    ignored_sorted = sorted(ignored_device_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ignored_top = [{"device": k, "count": v} for k, v in ignored_sorted[:_IGNORED_TOP_N]]
    ignored_total = sum(ignored_device_counts.values())
    included_parents_set = set(out_map.keys())
    included_clones_set: set[str] = set()
    for p in included_parents_set:
        for c in (parents_map.get(p) or []):
            included_clones_set.add(c)
    included_all = included_parents_set | included_clones_set
    gh_not_in_arcade_scope = sorted(gh_keys_with_ports - included_all)
    summary_ports = {
        "gh_arcade_entries_total": len(gh_ports),
        "gh_arcade_entries_with_ports_total": len(gh_keys_with_ports),
        "included_parents_after_ports_gate": len(out_map),
        "included_parents_with_own_ports": {
            "count": parents_with_ports_count,
            "note": "Included parents whose own GH shortname has ≥1 valid port row.",
        },
        "included_clones_with_ports": {
            "count": len(clones_with_ports_set),
            "list": sorted(clones_with_ports_set),
            "note": "Clone shortnames (children of included parents) with ≥1 valid GH port row.",
        },
        "gh_arcade_entries_with_ports_excluded_by_ini": {
            "count": len(gh_not_in_arcade_scope),
            "list": gh_not_in_arcade_scope,
            "note": "GH/MAME shortnames with ≥1 valid port row that are not in our Arcade/Game export.",
        },
    }
    parents_included_due_to_clones_only_list = sorted(
        m for m, rec in out_map.items()
        if not ((rec.get("ports") or {}).get("parent_source"))
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
    summary_ports["parent_clone_duplicate_ports"] = {
        "systems_count": systems_with_parent_clone_port_dupes,
        "systems_list": sorted(systems_with_parent_clone_port_dupes_list),
        "note": "Systems where at least one port row is identical between the parent GH entry and a clone GH entry (same category).",
        "note_duplicates": "Ports are not de-duplicated; identical parent/clone rows may appear intentionally for audit."
    }

    header_versions = dict({
        "mame_build":       mame_build_val,
        "history_version":  history_version_val,
        "history_date":     history_date_val,
        "ini_generated_at": ini_generated_at_val,
    })
    header_versions["transformer_version"] = tool_version("transformer")

    summary = {
        "header": {
            "schema_id": SCHEMA_IDS["transform"],
            "schema_version": schema_version(SCHEMA_IDS["transform"]),
            "generated_at": finished_utc,
            "started_utc": started_utc,
            "finished_utc": finished_utc,
            "duration_seconds": duration,
            "versions": header_versions,
        },
        "transformer_schema": TRANSFORMER_SCHEMA,
        "started_utc": started_utc,
        "finished_utc": finished_utc,
        "duration_seconds": duration,
        "inputs": inputs_map,
        "outputs": outputs_map,
        "versions": {
            "mame_build":       mame_build_val,
            "history_version":  history_version_val,
            "history_date":     history_date_val,
            "ini_generated_at": ini_generated_at_val,
        },
        "counts": {
            "mame_total": len(mame),
            "parents_total": parents_total,
            "clones_total": clones_total,
            "eligible_parents": len(eligible_parents),
            "final_included": len(out_map),
            "parents_with_clones": parents_with_clones,
            "total_clones_linked": total_clones_linked,
            "parents_without_clones": len(eligible_parents) - parents_with_clones,
            "parents_with_any_media": parents_with_any_media,
            "media_label_counts": media_label_counts_sorted,
            "audio": {
                "machines_reporting_channels": audio_total_with_channels,
                "channel_speaker_mismatches": audio_channel_speaker_mismatch,
                "mismatch_examples": audio_mismatch_examples,
                "machines_requiring_samples": audio_samples_required_count,
            },
        },
        "excluded_parents_by_reason": excluded_reasons,
        "included_flags": included_flags,
        "title_anomaly_counts": {k: len(v) for k, v in title_anomalies.items()},
        "title_anomalies": title_anomalies,
        "title_overrides": {
            "stats": overrides_stats,
            "applied": overrides_applied,
        },
        "ports": summary_ports,
        "notes": {
            "ports_attached": True,
            "export_scope": "Parents are exported only if INI says Arcade/Game AND the parent or any clone has ≥1 valid GH port row (platform present).",
            "filter_rules": {
                "game_status_equals": "game",
                "category_must_include": "Arcade",
                "ignore_coin_op_games": True,
                "ignore_type_for_filter": True,
                "ignore_isbios_isdevice_ismechanical_for_filter": True,
            },
            "title_parsing": {
                "numbered_fields": True,
                "global_version_is_single_string": True,
                "only_top_level_groups": True,
                "nested_preserved_inside": True,
            },
            "clones_list_title_source": "raw MAME 'description' (no overrides)",
            "ignored_media_devices": {
                "total_ignored_entries": ignored_total,
                "unique_ignored": len(ignored_device_counts),
                "top_ignored": ignored_top,
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
    if not set(summary_ports["gh_arcade_entries_with_ports_excluded_by_ini"]["list"]).issubset(set(gh_keys_with_ports)):
        log.warning("[ports] Excluded-by-INI list contains entries not in gh_keys_with_ports.")

    ok_sum = _write_json(TRANSFORM_SUMMARY, summary)

    save_stamp(stamp_path, current_stamp)
    log.info(f"Transformer completed in {duration:.2f}s "
             f"(eligible_parents={len(eligible_parents)}, included={len(out_map)})")
    return bool(ok_out and ok_sum)

# Stage stamps helpers (imported at end to avoid circular imports complaints in some setups)
from mht.utils.stamps import make_stamp, load_stamp, save_stamp, is_fresh

if __name__ == "__main__":
    ok = run_transformer(DATA_DIR)
    raise SystemExit(0 if ok else 1)
