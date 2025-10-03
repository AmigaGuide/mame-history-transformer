"""
Filename: transformer.py
Author: XtC

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
from mht.utils.headers import build_summary_header
from mht.utils.io import write_json
#from mht.title.parser import parse_description
from mht.utils.media import (
    normalise_device_to_media,
    normalise_device_list_to_media,
    order_media_labels,
    bytes_to_binary_human,
    join_with_ampersand,
)
from mht.utils.chips import (
    hz_to_human         as _hz_to_human,
    format_hz_3dp       as _format_hz_3dp,
    chip_label          as _chip_label,
    prefix_multiples    as _prefix_multiples,
    sum_device_speakers as _sum_device_speakers,
    has_samples_flag    as _has_samples_flag,
)
from mht.utils.controls import (
    pluralise                     as _pluralise,
    control_type_label            as _control_type_label,
    ways_pretty                   as _ways_pretty,
    ways_label                    as _ways_label,
    control_line_from_row         as _control_line_from_row,
    buttons_count_from_rows       as _buttons_count_from_rows,
    build_controls_section        as _build_controls_section,
    controls_section_to_display   as _controls_section_to_display,
)
from mht.utils.displays import (
    orientation_from_rotate      as _orientation_from_rotate,
    type_title                   as _type_title,
    format_hz_3dp                as _format_hz_3dp,
    build_displays_section       as _build_displays_section,
    displays_section_to_display  as _displays_section_to_display,
)
from mht.utils.ports import (
    canonical_port_key               as _canonical_port_key,
    has_parent_clone_duplicate_ports as _has_parent_clone_duplicate_ports,
    render_ports_display             as _render_ports_display,
    collect_valid_ports_by_category  as _collect_valid_ports_by_category,
    gh_keys_with_any_valid_ports     as _gh_keys_with_any_valid_ports,
    build_ports_for_parent           as _build_ports_for_parent,
    gh_ids_from_ports_obj            as _gh_ids_from_ports_obj,
)
from mht.utils.titles import (
    parse_description          as parse_description,
    find_unbalanced            as _find_unbalanced,
    wiki_page_name_from_desc   as _wiki_page_name_from_desc,
    build_redirect_sources     as _build_redirect_sources,
    unit_count_from_desc       as _unit_count_from_desc,
    collapse_ws                as _collapse_ws,
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
_VERSION_CORE_RX = re.compile(r"\d+(?:\.\d+)+")

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
    desc_fields, _ = parse_description(raw)
    return _primary_redirects_for_unit1(desc_fields, target_page_name)

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

def _read_gh_ports(path: Path) -> dict:
    data = _read_json(path)
    return data if isinstance(data, dict) else {}

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
    human = bytes_to_binary_human(total_bytes)
    line2 = f"{total_bytes:,} bytes" + (f" ({human[0]:.2f} {human[1]})" if human else "")
    line3 = None
    if (disk_required or "").lower() == "yes":
        seq = disk_regions if isinstance(disk_regions, (list, tuple)) else ([disk_regions] if disk_regions else [])
        all_labels: list[str] = []
        for raw in seq:
            lab = normalise_device_to_media(str(raw))
            if lab:
                all_labels.append(lab)
        if all_labels:
            counts = Counter(l.casefold() for l in all_labels)
            first_seen_unique = list(dict.fromkeys(all_labels))
            ordered_unique = order_media_labels(first_seen_unique)
            display_labels = []
            for lab in ordered_unique:
                n = counts[lab.casefold()]
                display_labels.append(f"({n}x) {lab}" if n > 1 else lab)
            line3 = f"Plus: {join_with_ampersand(display_labels)}"
    return "\n".join([line1, line2] + ([line3] if line3 else []))

def format_manufacturers_for_wiki(raw: str | None) -> str:
    parts = [p.strip() for p in _split_outside_parens(raw or "") if p.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} & {parts[1]}"
    return f"{', '.join(parts[:-1])} & {parts[-1]}"

def _pref(name: str, prefix: str = WIKI_PREFIX) -> str:
    return f"{prefix}{name}"

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
        _, pre_anoms = parse_description(raw_desc_original)
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
        desc_fields, _ = parse_description(raw_desc)
        wiki_page_name = _wiki_page_name_from_desc(desc_fields)
        raw_man = minfo.get("manufacturer") or ""
        manufacturer_display = join_with_ampersand(_split_outside_parens(raw_man))
        rom_count       = int(minfo.get("rom_count") or 0)
        rom_bytes_total = int(minfo.get("rom_bytes_total") or 0)
        disk_required = minfo.get("disk_required")
        disk_regions  = minfo.get("disk_regions")
        roms_display = _format_rom_block(rom_count, rom_bytes_total, disk_required, disk_regions)
        if (str(disk_required or "").lower() == "yes"):
            labels_for_counts = normalise_device_list_to_media(disk_regions)
            if labels_for_counts:
                parents_with_any_media += 1
                for lab in dict.fromkeys(labels_for_counts):
                    media_label_counts[lab] = media_label_counts.get(lab, 0) + 1
            seq = disk_regions if isinstance(disk_regions, (list, tuple)) else ([disk_regions] if disk_regions else [])
            for raw in seq:
                if normalise_device_to_media(str(raw)) is None:
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



    wiki_header = build_summary_header(
        schema_id=SCHEMA_ID_WIKI,
        schema_version=SCHEMA_VER_WIKI,
        versions=wiki_header_versions,
    )
    wiki_doc = {
        "header": wiki_header,
        "games": {m: _project_for_wiki(rec) for m, rec in out_map.items()},
    }
    #ok_out_wiki = write_json(EXOTICA_WIKI, wiki_doc)
    #ok_out_wiki = write_json(EXOTICA_WIKI, wiki_doc, sort_keys=False)
    ok_out_wiki = write_json(EXOTICA_WIKI, wiki_doc)


    raw_header = build_summary_header(
        schema_id=SCHEMA_ID_RAW,
        schema_version=SCHEMA_VER_RAW,
        versions=wiki_header_versions,
    )
    raw_doc = {
        "header": raw_header,
        "games": {m: _project_for_raw(m, rec) for m, rec in out_map.items()},
    }
    #ok_out_raw = write_json(EXOTICA_RAW, raw_doc)
    #ok_out_raw = write_json(EXOTICA_RAW, raw_doc, sort_keys=False)
    ok_out_raw  = write_json(EXOTICA_RAW,  raw_doc)

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
    
    pages_header = build_summary_header(
        schema_id=SCHEMA_ID_PAGES,
        schema_version=SCHEMA_VER_PAGES,
        #versions={},  # pages has no extra versions; leave empty
        versions=wiki_header_versions,  # include mame_xml_version, gaming_history_xml_version, ini_versions
    )
    
    wiki_pages_redirects = {
        "header": pages_header,
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
    #write_json(EXOTICA_PAGES, wiki_pages_redirects)
    ok_pages = write_json(EXOTICA_PAGES, wiki_pages_redirects)

    #ok_out = ok_out_wiki and ok_out_raw
    ok_out = ok_out_wiki and ok_out_raw and ok_pages

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



    summary_header = build_summary_header(
        schema_id=SCHEMA_IDS["transform"],
        schema_version=schema_version(SCHEMA_IDS["transform"]),
        versions=header_versions,
    )
    
    summary = {
        "header": summary_header,
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

    ok_sum = write_json(TRANSFORM_SUMMARY, summary)

    save_stamp(stamp_path, current_stamp)
    log.info(f"Transformer completed in {duration:.2f}s "
             f"(eligible_parents={len(eligible_parents)}, included={len(out_map)})")
    return bool(ok_out and ok_sum)

# Stage stamps helpers (imported at end to avoid circular imports complaints in some setups)
from mht.utils.stamps import make_stamp, load_stamp, save_stamp, is_fresh

if __name__ == "__main__":
    ok = run_transformer(DATA_DIR)
    raise SystemExit(0 if ok else 1)
