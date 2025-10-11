from __future__ import annotations
from pathlib import Path
import datetime
import time

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
from mht.utils.io import write_json, read_json as _read_json
from mht.utils.stamps import save_stamp, stage_is_fresh
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
    find_unbalanced          as _find_unbalanced,
    wiki_page_name_from_desc as _wiki_page_name_from_desc,
    build_redirect_sources   as _build_redirect_sources,
    unit_count_from_desc     as _unit_count_from_desc,
    collapse_ws              as _collapse_ws,
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
from mht.utils.records import (
    build_parent_record,
    project_for_wiki as _project_for_wiki, 
    project_for_raw  as _project_for_raw
)
from mht.utils.booleans import truthy_flag as _truthy_flag
from mht.utils.mame_titles import (
    _raw_mame_title,
    mame_titles_for_parent     as _mame_titles_for_parent,
    render_mame_titles_display as _render_mame_titles_display,
)    
from mht.utils.summaries import (
    build_transform_header,
    build_transform_summary,
    version_core as _core,
)
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

def run_transformer(data_dir: Path = DATA_DIR) -> bool:
    started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    t0 = time.perf_counter()

    # --- Stage stamp: skip unchanged (centralised helper) ---
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

    fresh, stamp_path, current_stamp = stage_is_fresh(
        "transform.json",
        schema_id="mht.stage.transform",
        tool="transformer",           # keep tool name stable for stamp lineage
        inputs=stamp_inputs,
    )
    if fresh:
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
    #gh_ports = _read_gh_ports(GH_SYSTEM_PORTS_PATH)
    gh_ports = _read_json(GH_SYSTEM_PORTS_PATH)
    gh_ports = gh_ports if isinstance(gh_ports, dict) else {}
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
        #raw_desc_original = _machine_title(minfo, name)
        raw_desc_original = _raw_mame_title(minfo, name)
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
        #mt_disp = _render_mame_titles_display(record.get("mame_titles", []))
        #if mt_disp:
        #    record["mame_titles_display"] = mt_disp
        mt_disp = _render_mame_titles_display(record["mame_titles"])
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

if __name__ == "__main__":
    ok = run_transformer(DATA_DIR)
    raise SystemExit(0 if ok else 1)
