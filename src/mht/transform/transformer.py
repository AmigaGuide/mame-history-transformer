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
    _chip_label,
    _prefix_multiples,
    sum_device_speakers as _sum_device_speakers,
    _has_samples_flag,
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
    render_ports_display,
    collect_valid_ports_by_category  as _collect_valid_ports_by_category,
    gh_keys_with_any_valid_ports     as _gh_keys_with_any_valid_ports,
    build_ports_for_parent           as _build_ports_for_parent,
    gh_ids_from_ports_obj            as _gh_ids_from_ports_obj,
)
from mht.utils.titles import (
    parse_description,
    find_unbalanced            as _find_unbalanced,
    wiki_page_name_from_desc   as _wiki_page_name_from_desc,
    build_redirect_sources     as _build_redirect_sources,
    unit_count_from_desc       as _unit_count_from_desc,
    collapse_ws                as _collapse_ws,
)
from mht.utils.strings import format_manufacturers_for_wiki, split_outside_parens
from mht.utils.wiki_pages import compute_pages_and_redirects
from mht.utils.roms import format_rom_block
from mht.utils.selection import (
    classify as _classify,
    is_eligible_parent as _is_eligible_parent,
    build_final_set as _build_final_set,
)
from mht.utils.mame_overrides import (
    load_title_overrides as _load_title_overrides,
    apply_title_override_if_eligible,
    dedupe_anomalies_preferring_pre_override as _dedupe_anomalies_preferring_pre_override,
)
from mht.utils.records import build_parent_record
from mht.utils.booleans import truthy_flag as _truthy_flag
from mht.utils.mame_titles import (
    mame_titles_for_parent as _mame_titles_for_parent,
    _raw_mame_title
)    
from mht.utils.summaries import build_transform_header, build_transform_summary
from mht.utils.redirects import (
    clone_primary_redirects as _clone_primary_redirects,
    dedupe_ci_preserve_order as _dedupe_ci_preserve_order,
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

def _pref(name: str, prefix: str = WIKI_PREFIX) -> str:
    return f"{prefix}{name}"

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
        raw_desc, applied, eligible = apply_title_override_if_eligible(name, raw_desc_original, overrides)

        if eligible:
            overrides_stats["eligible"] += 1
        if applied:
            overrides_applied.append(applied)
            overrides_stats["applied"] += 1
            
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

        # Build the full per-parent record and gather telemetry (media/audio/ports)
        record, t = build_parent_record(
            parent_name=name,
            mame=mame,
            ini_map=ini_map,
            parent_index=parent_index,
            gh_ports=gh_ports,
            desc_fields=desc_fields,
            wiki_page_name=wiki_page_name,
        )

        # If neither parent nor its clones has valid GH ports, skip this parent
        if not record:
            continue

        # Optional: MAME titles display (keep your existing helper)
        mt_disp = _render_mame_titles_display(record.get("mame_titles", []))
        if mt_disp:
            record["mame_titles_display"] = mt_disp

        # Build wiki redirects (use whichever helper name you already import)
        try:
            parent_redirects = build_redirect_sources(desc_fields, wiki_page_name)
        except NameError:
            # Back-compat if your helper is still named _build_redirect_sources
            parent_redirects = _build_redirect_sources(desc_fields, wiki_page_name)

        # Also add clone-based primary redirects that point to this parent page
        clone_redirects: list[str] = []
        for cs in (record.get("ports", {}) or {}).get("clone_sources", []) or []:
            c_machine = (cs or {}).get("machine")
            if not c_machine:
                continue
            clone_redirects.extend(_clone_primary_redirects(c_machine, mame, wiki_page_name))

        # Merge/normalise redirects (case-insensitive de-dupe, exclude exact target)
        merged_redirects: list[str] = []
        target_ci = (wiki_page_name or "").casefold()
        for s in (parent_redirects + clone_redirects):
            n = _collapse_ws(s)
            if n and n.casefold() != target_ci:
                merged_redirects.append(n)
        record["wiki_redirects"] = _dedupe_ci_preserve_order(merged_redirects)

        # Ports display lines for wiki (parent+clone rows, date-ordered per category)
        ports_display = render_ports_display(name, record.get("ports") or {})
        if ports_display:
            record["ports_display"] = ports_display

        # ---- Aggregate telemetry into your existing counters ----

        # Media tallies
        if t["parents_with_any_media"]:
            parents_with_any_media += 1
        for lab in t["media_labels_for_counts"]:
            media_label_counts[lab] = media_label_counts.get(lab, 0) + 1
        for dev, cnt in t["ignored_devices"].items():
            ignored_device_counts[dev] = ignored_device_counts.get(dev, 0) + cnt

        # Audio tallies & mismatch examples
        if t["audio_channels_reported"] > 0:
            audio_total_with_channels += 1
            if t["speaker_sum"] != t["audio_channels_reported"]:
                audio_channel_speaker_mismatch += 1
                if len(audio_mismatch_examples) < 10:
                    audio_mismatch_examples.append({
                        "machine": name,
                        "sound_channels": t["audio_channels_reported"],
                        "speaker_sum": t["speaker_sum"]
                    })
        if t["samples_required"]:
            audio_samples_required_count += 1

        # Ports tallies
        if t["parent_has_ports"]:
            parents_with_ports_count += 1
        clones_with_ports_set.update(t["clones_with_ports"])
        if t["has_parent_clone_port_dupes"]:
            systems_with_parent_clone_port_dupes += 1
            systems_with_parent_clone_port_dupes_list.append(name)

        # Keep the record
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
    ok_out_raw  = write_json(EXOTICA_RAW,  raw_doc)

    parents_total = sum(1 for v in mame.values() if not v.get("cloneof"))
    clones_total  = sum(1 for v in mame.values() if v.get("cloneof"))

    # --- Build pages + redirects (now via helper) ---
    generated_at_iso = datetime.datetime.utcnow().isoformat() + "Z"

    pages_info = compute_pages_and_redirects(out_map, WIKI_PREFIX)

    wiki_pages_redirects = {
        "header": {
            "schema_id": SCHEMA_ID_PAGES,
            "schema_version": SCHEMA_VER_PAGES,
            "generated_at": generated_at_iso,
        },
        "prefix": WIKI_PREFIX,
        "stats": pages_info["stats"],
        "pages": pages_info["pages"],
        "page_names": pages_info["page_names"],
        "redirects": pages_info["redirects"],
        "conflicts": pages_info["conflicts"],
    }
    ok_pages = write_json(EXOTICA_PAGES, wiki_pages_redirects)

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


    # --- Build standard header for the transform summary
    header = build_transform_header(
        versions={
            "mame_build":       mame_build_val,
            "history_version":  history_version_val,
            "history_date":     history_date_val,
            "ini_generated_at": ini_generated_at_val,
            # transformer_version is added automatically if missing
        },
        started_utc=started_utc,
        finished_utc=finished_utc,
        duration_seconds=duration,
    )

    # Inputs/outputs maps are already constructed earlier as `inputs_map` and `outputs_map`

    summary = build_transform_summary(
        header=header,
        inputs=inputs_map,
        outputs=outputs_map,

        # Sets / maps
        out_map=out_map,
        parents_map=parents_map,

        # Universe counts
        mame_total=len(mame),
        parents_total=parents_total,
        clones_total=clones_total,
        eligible_parents=eligible_parents,

        # Media / audio telemetry (use your existing variables)
        media_label_counts=media_label_counts,
        parents_with_any_media=parents_with_any_media,
        audio={
            "machines_reporting_channels": audio_total_with_channels,
            "channel_speaker_mismatches": audio_channel_speaker_mismatch,
            "mismatch_examples": audio_mismatch_examples,
            "machines_requiring_samples": audio_samples_required_count,
        },

        # Ports block (already assembled earlier)
        ports=summary_ports,

        # Optional diagnostics / mirrors (use your existing dicts)
        excluded_parents_by_reason=excluded_reasons,
        included_flags=included_flags,
        title_anomalies=title_anomalies,
        title_overrides={
            "stats": overrides_stats,
            "applied": overrides_applied,
        },
        errors=[] if ok_out and not missing_in_mame else (
            [{"missing_in_mame": missing_in_mame}] if missing_in_mame else []
        ),
    )


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
