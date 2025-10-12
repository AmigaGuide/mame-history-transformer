from __future__ import annotations

from pathlib import Path
import datetime
import time
from typing import Dict, Any, List

from mht.utils.config import LOG_LEVEL, _IGNORED_TOP_N
from mht.utils.logger import setup_logger, debug_log, maybe_log_progress
from mht.utils.versions import SCHEMA_IDS, schema_version, output_schema
from mht.utils.paths import (
    DATA_DIR,
    # summaries
    MAME_SUMMARY, HISTORY_SUMMARY, INI_SUMMARY, TRANSFORM_SUMMARY,
    # intermediates / inputs
    MAME_MACHINES_PATH, PARENT_INDEX_PATH, GH_SYSTEM_PORTS_PATH, INI_CLASS_PATH,
    # finals
    EXOTICA_WIKI, EXOTICA_RAW, EXOTICA_PAGES,
)
from mht.utils.headers import build_summary_header
from mht.utils.io import write_json
from mht.utils.stamps import save_stamp, stage_is_fresh
from mht.utils.ports import (
    render_ports_display,
    gh_keys_with_any_valid_ports     as _gh_keys_with_any_valid_ports,
)
from mht.utils.titles import (
    parse_description,
    wiki_page_name_from_desc as _wiki_page_name_from_desc,
    build_redirect_sources   as _build_redirect_sources,
    collapse_ws              as _collapse_ws,
)
from mht.utils.wiki_pages import WIKI_PREFIX, write_pages_and_redirects
from mht.utils.selection import (
    build_final_set as _build_final_set,
    build_eligible_parents_set,
    universe_parent_clone_counts,
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
from mht.utils.mame_titles import (
    _raw_mame_title,
    render_mame_titles_display as _render_mame_titles_display,
)    
from mht.utils.summaries import (
    build_transform_header,
    build_transform_summary,
    extract_stage_versions_for_transform,
    build_selection_telemetry,
    build_displays_shape_telemetry,
    build_ports_telemetry,
)
from mht.utils.redirects import (
    clone_primary_redirects as _clone_primary_redirects,
    dedupe_ci_preserve_order as _dedupe_ci_preserve_order,
)
from mht.utils.transform_io import load_stage_inputs, build_inputs_map, build_outputs_map


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

    mame_machines, parent_index, gh_system_ports, ini_classifications = load_stage_inputs()    
    # Normalise inputs to dicts and bind to names the rest of the file expects
    mame     = mame_machines or {}
    ini_map  = ini_classifications or {}
    gh_ports = gh_system_ports or {}
    parent_index = parent_index or {}

    gh_keys_with_ports = _gh_keys_with_any_valid_ports(gh_ports)

    if not isinstance(mame, dict) or not isinstance(ini_map, dict) or not isinstance(parent_index, dict):
        log.error("Missing or invalid inputs; aborting transform.")
        return False

    parents_map: Dict[str, list] = (parent_index or {}).get("parents", {})

    versions, wiki_header_versions = extract_stage_versions_for_transform(
        MAME_SUMMARY, HISTORY_SUMMARY, INI_SUMMARY
    )
   
    # Compute the final parent set via the central selection helper
    _result = _build_final_set(mame, ini_map)

    # Support either signature: Set[str] or (eligible_set, included_set, excluded_reasons)
    if isinstance(_result, tuple) and len(_result) >= 2:
        eligible_parents, included_parents = _result[0], _result[1]
        # Optional third return: reasons dict; keep if provided, else preserve existing local dict
        if len(_result) >= 3 and isinstance(_result[2], dict):
            excluded_reasons = _result[2]
    else:
        included_parents = set(_result)
        eligible_parents = build_eligible_parents_set(mame, ini_map)
            
    # A tiny sanity log (debug)
    debug_log(f"[transform::pipeline] eligible={len(eligible_parents):,}, included={len(included_parents):,}")

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
    audio_total_with_channels = 0
    audio_channel_speaker_mismatch = 0
    audio_mismatch_examples: list[dict] = []
    audio_samples_required_count = 0
    parents_with_ports_count = 0
    clones_with_ports_set: set[str] = set()
    assembled_count = 0

    for name in sorted(included_parents):
        minfo = mame.get(name)
        if not minfo:
            continue        
        # --- Titles: original → pre-override anomalies → single override → parse final ---
        raw_desc_original = _raw_mame_title(minfo, name)

        # Capture pre-override anomalies from the original description
        _, pre_anoms = parse_description(raw_desc_original)
        for k, lst in pre_anoms.items():
            for item in lst:
                item["machine"] = name
                item["pre_override"] = True
            title_anomalies[k].extend(lst)

        # Apply title override (once) and track stats
        raw_desc, applied, eligible = apply_title_override_if_eligible(name, raw_desc_original, overrides)
        if eligible:
            overrides_stats["eligible"] += 1
        if applied:
            overrides_applied.append(applied)
            overrides_stats["applied"] += 1

        # Parse the final (possibly overridden) description and derive page name
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

        assembled_count += 1
        maybe_log_progress(
            log,
            assembled_count,
            step=250,
            prefix="[transform::pipeline]",
            fmt="{prefix} Assembled {count:,} parent records so far...",
        )

        # Optional: MAME titles display (keep your existing helper)
        mt_disp = _render_mame_titles_display(record["mame_titles"])
        if mt_disp:
            record["mame_titles_display"] = mt_disp

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

    # Final progress summary (assembled vs eligible)
    log.info(
        "[transform::pipeline] Assembled %s parent records (out of %s eligible).",
        f"{assembled_count:,}",
        f"{len(included_parents):,}",
    )

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

    parents_total, clones_total = universe_parent_clone_counts(mame)

    # --- Build pages + redirects (now via helper) ---
    ok_pages, pages_info = write_pages_and_redirects(
        out_map=out_map,
        prefix=WIKI_PREFIX,
        schema_id=SCHEMA_ID_PAGES,
        schema_version=SCHEMA_VER_PAGES,
        output_path=EXOTICA_PAGES,
    )

    ok_out = ok_out_wiki and ok_out_raw and ok_pages

    finished_utc = datetime.datetime.utcnow().isoformat() + "Z"
    duration = round(time.perf_counter() - t0, 3)

    inputs_map = build_inputs_map(have_overrides=have_overrides, overrides_path=overrides_path)
    outputs_map = build_outputs_map()

    #parents_with= sum(
    #    1 for r in out_map.values()
    #    if any(t.get("role") == "clone" for t in r.get("mame_titles", []))
    #)
    #total_clones_linked = sum(
    #    sum(1 for t in r.get("mame_titles", []) if t.get("role") == "clone")
    #    for r in out_map.values()
    #)

    title_anomalies = _dedupe_anomalies_preferring_pre_override(title_anomalies)
    #title_anomaly_counts = {k: len(v) for k, v in title_anomalies.items()}
    #media_label_counts_sorted = dict(sorted(media_label_counts.items(), key=lambda kv: kv[0].casefold()))
    ignored_sorted = sorted(ignored_device_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ignored_top = [{"device": k, "count": v} for k, v in ignored_sorted[:_IGNORED_TOP_N]]
    #ignored_total = sum(ignored_device_counts.values())
    included_parents_set = set(out_map.keys())
    included_clones_set: set[str] = set()
    for p in included_parents_set:
        for c in (parents_map.get(p) or []):
            included_clones_set.add(c)
    included_all = included_parents_set | included_clones_set
    gh_not_in_arcade_scope = sorted(gh_keys_with_ports - included_all)
    
    summary_ports = build_ports_telemetry(
        gh_ports=gh_ports,
        gh_keys_with_ports=gh_keys_with_ports,
        out_map=out_map,
        parents_map=parents_map,
        parents_with_ports_count=parents_with_ports_count,
        clones_with_ports_set=clones_with_ports_set,
        systems_with_parent_clone_port_dupes=systems_with_parent_clone_port_dupes,
        systems_with_parent_clone_port_dupes_list=systems_with_parent_clone_port_dupes_list,
        gh_not_in_arcade_scope=gh_not_in_arcade_scope,
    )

    selection_telemetry = build_selection_telemetry(
        out_map=out_map,
        eligible_parents=eligible_parents,
        excluded_parents_by_reason=excluded_reasons,
    )

    displays_shape_telemetry = build_displays_shape_telemetry(out_map)

    # --- Build standard header for the transform summary
    header = build_transform_header(
        versions=versions,  # from extract_stage_versions_for_transform
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

    summary["selection"] = selection_telemetry
    summary["displays_shape"] = displays_shape_telemetry

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
