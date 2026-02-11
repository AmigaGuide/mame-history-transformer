"""
Transform pipeline (per-release)

Joins MAME, History XML (PORTS), and INI classifications to produce the
ExoticA LiT outputs **under the active release**:

- data/releases/<ver>/outputs/exotica_lit_wiki.json
- data/releases/<ver>/outputs/exotica_lit_raw_data.json
- data/releases/<ver>/outputs/exotica_wiki_pages_and_redirects.json
- data/releases/<ver>/summaries/transform_summary.json
- data/releases/<ver>/.stamps/transform.json

The stage is incremental: it writes a stamp and skips work when inputs and
tool version are unchanged.
"""

from __future__ import annotations

import datetime
import time
from typing import Dict, Any, List
import json
from pathlib import Path

from mht.utils.config import LOG_LEVEL
from mht.utils.logger import setup_logger, debug_log, maybe_log_progress
from mht.utils.versions import SCHEMA_IDS, schema_version, output_schema
from mht.utils.paths import (
    # release-aware dirs/files
    ensure_release_dirs,
    title_overrides_path,
    mame_summary_path, history_summary_path, ini_summary_path, transform_summary_path,
    mame_machines_path, parent_index_path, gh_system_ports_path, ini_classifications_path,
    exotica_wiki_path, exotica_raw_path, exotica_pages_path,
    stamps_dir,
)
from mht.utils.headers import build_summary_header
from mht.utils.io import write_json, file_meta
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
    inherit_parent_classification_for_clones,
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

# --- stamp + file meta helpers (add near imports) ---

def _records_in_dict_json(p: Path) -> int | None:
    """
    Return len(dict) if the JSON root is a dict, else None.
    Used for input artefacts like mame_machines.json and gh_ini_classifications.json.
    """
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return len(obj) if isinstance(obj, dict) else None
    except Exception:
        return None

def _read_summary_compact(p: Path) -> dict:
    """
    Read an upstream parsing summary and return only the bits Transform cares about.
    Safe: returns {} on any failure.
    """
    try:
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f) or {}
        header = doc.get("header") or {}
        prov = doc.get("provenance") or {}
        return {
            "header": header,
            "provenance": {
                "inputs": prov.get("inputs") or []
            },
        }
    except Exception:
        return {}

def _records_in_wiki_or_raw_json(p: Path) -> int | None:
    try:
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f) or {}
        games = doc.get("games")
        if isinstance(games, dict):
            return len(games)
    except Exception:
        pass
    return None

def _build_ports_ini_coverage_telemetry(
    *,
    mame: Dict[str, Any],
    parent_index: Dict[str, Any],
    gh_ports: Dict[str, Any],
    gh_keys_with_ports: set[str] | List[str] | None,
    ini_map: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build telemetry about how History (GH) systems with ports intersect with:

      - MAME parent/clone roles, and
      - INI coverage (gh_ini_classifications.json).

    This is purely diagnostic: it does not affect selection or output content.
    """
    # Normalise to sets
    ports_keys: set[str] = set(gh_keys_with_ports or [])
    ini_keys: set[str] = set((ini_map or {}).keys())
    history_systems: set[str] = set((gh_ports or {}).keys())

    # Systems with ports that do / do not appear in the INI classifications
    ports_missing_ini: set[str] = ports_keys - ini_keys
    ports_present_ini: set[str] = ports_keys & ini_keys

    # Classify systems-with-ports by MAME role (parent / clone / unknown)
    ports_parents: set[str] = set()
    ports_clones: set[str] = set()
    ports_unknown_in_mame: set[str] = set()

    for name in ports_keys:
        minfo = (mame or {}).get(name)
        if not isinstance(minfo, dict):
            ports_unknown_in_mame.add(name)
            continue
        if minfo.get("cloneof"):
            ports_clones.add(name)
        else:
            ports_parents.add(name)

    ports_parents_missing_ini: set[str] = ports_parents & ports_missing_ini
    ports_clones_missing_ini: set[str] = ports_clones & ports_missing_ini
    ports_unknown_missing_ini: set[str] = ports_unknown_in_mame & ports_missing_ini

    # INI coverage by MAME role (are INIs mostly parents-only?)
    ini_parents: set[str] = set()
    ini_clones: set[str] = set()
    ini_unknown_in_mame: set[str] = set()

    for name in ini_keys:
        minfo = (mame or {}).get(name)
        if not isinstance(minfo, dict):
            ini_unknown_in_mame.add(name)
            continue
        if minfo.get("cloneof"):
            ini_clones.add(name)
        else:
            ini_parents.add(name)

    # History systems that do not appear in the INI map at all
    history_missing_ini: set[str] = history_systems - ini_keys

    coverage: Dict[str, Any] = {
        # How many GH systems have usable PORTS, by MAME role
        "systems_with_ports_total": len(ports_keys),
        "parents_with_ports_total": len(ports_parents),
        "clones_with_ports_total": len(ports_clones),
        "systems_with_ports_unknown_in_mame_total": len(ports_unknown_in_mame),

        # INI coverage for systems-with-ports
        "systems_with_ports_with_ini_total": len(ports_present_ini),
        "systems_with_ports_missing_ini_total": len(ports_missing_ini),
        "parents_with_ports_missing_ini_total": len(ports_parents_missing_ini),
        "clones_with_ports_missing_ini_total": len(ports_clones_missing_ini),
        "unknown_in_mame_with_ports_missing_ini_total": len(ports_unknown_missing_ini),

        # History vs INI coverage (all systems, not just those with PORTS)
        "history_systems_total": len(history_systems),
        "history_systems_missing_ini_total": len(history_missing_ini),

        # INI contents by MAME role
        "ini_machines_total": len(ini_keys),
        "ini_parents_total": len(ini_parents),
        "ini_clones_total": len(ini_clones),
        "ini_unknown_in_mame_total": len(ini_unknown_in_mame),
    }

    # Optionally embed concrete name lists when they are small enough to be inspectable
    max_list = 200

    if 0 < len(ports_missing_ini) <= max_list:
        coverage["systems_with_ports_missing_ini"] = sorted(ports_missing_ini)

    if 0 < len(history_missing_ini) <= max_list:
        coverage["history_systems_missing_ini"] = sorted(history_missing_ini)

    debug_log(
        "[transform::ports] "
        f"systems_with_ports={len(ports_keys)}, "
        f"ports_missing_ini={len(ports_missing_ini)}, "
        f"history_missing_ini={len(history_missing_ini)}"
    )

    return coverage

def run_transformer() -> bool:
    """
    Execute the transform stage end-to-end for the **active release**.

    Returns True when all artefacts and the summary are written and the stamp
    is saved; False on any write/validation failure.
    """
    # Ensure per-release dirs exist (noop if already there)
    ensure_release_dirs()

    started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    t0 = time.perf_counter()

    # --- Stage stamp: skip unchanged (centralised helper) ---
    stamp_inputs = [
        mame_machines_path(),
        ini_classifications_path(),
        parent_index_path(),
        gh_system_ports_path(),
        mame_summary_path(),
        history_summary_path(),
        ini_summary_path(),
        title_overrides_path(),
    ]

    fresh, stamp_path, current_stamp = stage_is_fresh(
        "transform.json",
        schema_id="mht.stage.transform",
        tool="transformer",
        inputs=stamp_inputs,
        stamps_dir=stamps_dir(),
    )   
    if fresh:
        log.info("Transform stage up-to-date (stamp matched) — skipping transform")
        return True

    wiki_header_versions = {
        "mame_xml_version": "Unknown",
        "gaming_history_xml_version": "Unknown",
        "ini_versions": {}
    }

    overrides_path = title_overrides_path()
    overrides = _load_title_overrides(overrides_path)
    have_overrides = isinstance(overrides, dict) and bool(overrides)
    overrides_applied: list[dict[str, str]] = []
    overrides_stats = {"configured": len(overrides) if isinstance(overrides, dict) else 0, "eligible": 0, "applied": 0}
   
    mame_machines, parent_index, gh_system_ports, ini_classifications = load_stage_inputs()

    # Normalise inputs to dicts and bind to names the rest of the file expects
    mame       = mame_machines or {}
    ini_raw    = ini_classifications or {}   # raw gh_ini_classifications.json (parents only)
    gh_ports   = gh_system_ports or {}
    parent_index = parent_index or {}

    # For transform-time classification, let clones inherit their parent's
    # INI row when the parent exists in ini_raw but the clone does not.
    ini_map = inherit_parent_classification_for_clones(ini_raw, parent_index)

    gh_keys_with_ports = _gh_keys_with_any_valid_ports(gh_ports)
   
    if not isinstance(mame, dict) or not isinstance(ini_map, dict) or not isinstance(parent_index, dict):
        log.error("Missing or invalid inputs; aborting transform.")
        return False

    parents_map: Dict[str, list] = (parent_index or {}).get("parents", {})

    versions, wiki_header_versions = extract_stage_versions_for_transform(
        mame_summary_path(), history_summary_path(), ini_summary_path()
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
            excluded_reasons = {"not_game": 0, "not_arcade": 0, "unknown_classification": 0}
    else:
        included_parents = set(_result)
        eligible_parents = build_eligible_parents_set(mame, ini_map)
        excluded_reasons = {"not_game": 0, "not_arcade": 0, "unknown_classification": 0}

    debug_log(f"[transform::pipeline] eligible={len(eligible_parents):,}, included={len(included_parents):,}")

    out_map: Dict[str, Dict[str, Any]] = {}
    included_flags = {"isbios": 0, "isdevice": 0, "ismechanical": 0}
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

        # Optional: MAME titles display
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

        # Ports display lines for wiki
        ports_display = render_ports_display(name, record.get("ports") or {})
        if ports_display:
            record["ports_display"] = ports_display

        # ---- Aggregate telemetry ----
        if t["parents_with_any_media"]:
            parents_with_any_media += 1
        for lab in t["media_labels_for_counts"]:
            media_label_counts[lab] = media_label_counts.get(lab, 0) + 1
        for dev, cnt in t["ignored_devices"].items():
            ignored_device_counts[dev] = ignored_device_counts.get(dev, 0) + cnt

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

        if t["parent_has_ports"]:
            parents_with_ports_count += 1
        clones_with_ports_set.update(t["clones_with_ports"])
        if t["has_parent_clone_port_dupes"]:
            systems_with_parent_clone_port_dupes += 1
            systems_with_parent_clone_port_dupes_list.append(name)

        out_map[name] = record

    log.info(
        "[transform::pipeline] Assembled %s parent records (out of %s eligible).",
        f"{len(out_map):,}",
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
    ok_out_wiki = write_json(exotica_wiki_path(), wiki_doc, sort_keys=False)

    raw_header = build_summary_header(
        schema_id=SCHEMA_ID_RAW,
        schema_version=SCHEMA_VER_RAW,
        versions=wiki_header_versions,
    )
    raw_doc = {
        "header": raw_header,
        "games": {m: _project_for_raw(m, rec) for m, rec in out_map.items()},
    }
    ok_out_raw  = write_json(exotica_raw_path(),  raw_doc,  sort_keys=False)

    parents_total, clones_total = universe_parent_clone_counts(mame)

    # --- Build pages + redirects ---    
    ok_pages, pages_info = write_pages_and_redirects(
        out_map=out_map,
        prefix=WIKI_PREFIX,
        schema_id=SCHEMA_ID_PAGES,
        schema_version=SCHEMA_VER_PAGES,
        output_path=exotica_pages_path(),
    )    
    
    ok_out = ok_out_wiki and ok_out_raw and ok_pages

    finished_utc = datetime.datetime.utcnow().isoformat() + "Z"
    duration = round(time.perf_counter() - t0, 3)

    inputs_map = build_inputs_map(have_overrides=have_overrides)
    outputs_map = build_outputs_map()

    title_anomalies = _dedupe_anomalies_preferring_pre_override(title_anomalies)
    # (removed unused `ignored_sorted` assignment)

    included_parents_set = set(out_map.keys())
    included_clones_set: set[str] = set()
    for p in included_parents_set:
        for c in ( (parents_map := (parent_index or {}).get("parents", {})).get(p) or [] ):
            included_clones_set.add(c)
    included_all = included_parents_set | included_clones_set
    gh_keys_with_ports = gh_keys_with_ports  # name remains for clarity
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

    # Coverage stats showing how GH systems-with-ports intersect with
    # MAME parent/clone roles and INI classifications.
    ports_ini_coverage = _build_ports_ini_coverage_telemetry(
        mame=mame,
        parent_index=parent_index,
        gh_ports=gh_ports,
        gh_keys_with_ports=gh_keys_with_ports,
        ini_map=ini_raw,
    )
    summary_ports["ini_and_history_coverage"] = ports_ini_coverage

    selection_telemetry = build_selection_telemetry(
        out_map=out_map,
        eligible_parents=eligible_parents,
        excluded_parents_by_reason=excluded_reasons,
    )

    displays_shape_telemetry = build_displays_shape_telemetry(out_map)

    header = build_transform_header(
        versions=versions,
        started_utc=started_utc,
        finished_utc=finished_utc,
        duration_seconds=duration,
    )

    # --- NEW: Transform provenance (consumed artefacts) ---
    provenance_inputs = []
    for p in (
        mame_machines_path(),
        parent_index_path(),
        gh_system_ports_path(),
        ini_classifications_path(),
        title_overrides_path(),
    ):
        try:
            if p and p.exists():
                meta = file_meta(p)
                # Optional lightweight record counts for JSON dict roots
                recs = _records_in_dict_json(p)
                if recs is not None:
                    meta["records"] = recs
                provenance_inputs.append(meta)
            else:
                provenance_inputs.append({"path": p.as_posix() if isinstance(p, Path) else str(p), "missing": True})
        except Exception:
            provenance_inputs.append({"path": p.as_posix() if isinstance(p, Path) else str(p), "error": "stat-failed"})

    upstream_summaries = {
        "mame": _read_summary_compact(mame_summary_path()),
        "history": _read_summary_compact(history_summary_path()),
        "ini": _read_summary_compact(ini_summary_path()),
    }

    provenance = {
        "inputs": provenance_inputs,
        "upstream_summaries": upstream_summaries,
    }

    # --- Provenance: outputs produced by this stage ---
    provenance_outputs = []

    def _add_output_meta(p: Path, extra: dict | None = None):
        if p.exists():
            meta = file_meta(p)
            if extra:
                meta.update(extra)
            provenance_outputs.append(meta)

    _add_output_meta(
        exotica_wiki_path(),
        {"records": _records_in_wiki_or_raw_json(exotica_wiki_path())},
    )

    _add_output_meta(
        exotica_raw_path(),
        {"records": _records_in_wiki_or_raw_json(exotica_raw_path())},
    )

    provenance["outputs"] = provenance_outputs

    # --- Pages artefact counts for provenance.outputs ---
    if isinstance(pages_info, dict):
        stats = pages_info.get("stats")
        if isinstance(stats, dict):
            # Prefer explicit stat keys if present
            pages_count = stats.get("pages_count")
            redirects_count = stats.get("redirects_count")
            conflicts_count = stats.get("conflicts_count")

        # Fallback to lengths if still unknown
        def _len_if_sized(x):
            return len(x) if isinstance(x, (list, dict)) else None

        pages_list = pages_info.get("pages")
        redirects_list = pages_info.get("redirects")
        conflicts_list = pages_info.get("conflicts")

        if pages_count is None:
            pages_count = _len_if_sized(pages_list)
        if redirects_count is None:
            redirects_count = _len_if_sized(redirects_list)
        if conflicts_count is None:
            conflicts_count = _len_if_sized(conflicts_list)

        # Fallback to lengths if still unknown (works even if stats keys differ)
        def _len_if_sized(x):
            return len(x) if isinstance(x, (list, dict)) else None

        pages_count = _len_if_sized(pages_list)
        redirects_count = _len_if_sized(redirects_list)
        conflicts_count = _len_if_sized(conflicts_list)


    _add_output_meta(
        exotica_pages_path(),
        {
            "pages_count": pages_count,
            "redirects_count": redirects_count,
            "conflicts_count": conflicts_count,
        },
    )


    summary = build_transform_summary(
        header=header,
        inputs=inputs_map,
        outputs=outputs_map,
        out_map=out_map,
        parents_map=parents_map,
        mame_total=len(mame),
        parents_total=parents_total,
        clones_total=clones_total,
        eligible_parents=eligible_parents,
        media_label_counts=media_label_counts,
        parents_with_any_media=parents_with_any_media,
        audio={
            "machines_reporting_channels": audio_total_with_channels,
            "channel_speaker_mismatches": audio_channel_speaker_mismatch,
            "mismatch_examples": audio_mismatch_examples,
            "machines_requiring_samples": audio_samples_required_count,
        },
        ports=summary_ports,
        excluded_parents_by_reason=excluded_reasons,
        included_flags=included_flags,  # use the computed variable
        title_anomalies=title_anomalies,
        title_overrides={"stats": overrides_stats, "applied": overrides_applied},
        errors=[],
    )

    # Ensure consistent top-level ordering: header -> provenance -> rest
    if isinstance(summary, dict):        
        summary = {
            "header": summary.get("header"),
            "provenance": provenance,
            **{k: v for k, v in summary.items() if k not in ("header", "provenance")},
        }
        
    summary["selection"] = selection_telemetry
    summary["displays_shape"] = displays_shape_telemetry

    ok_sum = write_json(transform_summary_path(), summary, sort_keys=False)

    # Optional: include transform_summary.json itself (requires a second write)
    if ok_sum:
        try:
            p = transform_summary_path()
            if p.exists():
                provenance_outputs.append(file_meta(p))
                provenance["outputs"] = provenance_outputs
                summary["provenance"] = provenance
                ok_sum = write_json(p, summary, sort_keys=False)
        except Exception:
            pass

    # --- Build a rich stamp mirroring other stages ---
    stamp_doc = dict(current_stamp)  # keep the freshness core intact

    # Inputs detail: include meta (size/sha256/mtime) for every input you keyed freshness on
    inputs_detail = []
    for p in stamp_inputs:
        try:
            if p and p.exists():
                inputs_detail.append(file_meta(p))
            else:
                inputs_detail.append({"path": p.as_posix() if isinstance(p, Path) else str(p), "missing": True})
        except Exception:
            inputs_detail.append({"path": p.as_posix() if isinstance(p, Path) else str(p), "error": "stat-failed"})

    # Outputs detail: wiki/raw/pages + summary, with record counts where sensible
    outputs = []

    wiki_fp = exotica_wiki_path()
    if wiki_fp.exists():
        w = file_meta(wiki_fp)
        w["records"] = _records_in_wiki_or_raw_json(wiki_fp)
        outputs.append(w)

    raw_fp = exotica_raw_path()
    if raw_fp.exists():
        r = file_meta(raw_fp)
        r["records"] = _records_in_wiki_or_raw_json(raw_fp)
        outputs.append(r)

    pages_fp = exotica_pages_path()
    if pages_fp.exists():
        pmeta = file_meta(pages_fp)

        stats = {}
        if isinstance(pages_info, dict):
            stats = pages_info.get("stats") or {}
        if not isinstance(stats, dict):
            stats = {}

        pmeta.update({
            "pages_count": stats.get("pages_count"),
            "redirects_count": stats.get("redirects_count"),
            "conflicts_count": stats.get("conflicts_count"),
        })

        outputs.append(pmeta)


        def _len_if_list(x):
            return len(x) if isinstance(x, list) else None

        if pmeta["pages_count"] is None and isinstance(pages_info, dict):
            pmeta["pages_count"] = _len_if_list(pages_info.get("pages"))
        if pmeta["redirects_count"] is None and isinstance(pages_info, dict):
            pmeta["redirects_count"] = _len_if_list(pages_info.get("redirects"))
        if pmeta["conflicts_count"] is None and isinstance(pages_info, dict):
            pmeta["conflicts_count"] = _len_if_list(pages_info.get("conflicts"))



    ts_fp = transform_summary_path()
    if ts_fp.exists():
        outputs.append(file_meta(ts_fp))

    # Stats: pull key figures you already computed (small, useful set)
    stats = {
        "eligible_parents":                len(eligible_parents),
        "included_parents":                len(out_map),
        "parents_with_ports":              parents_with_ports_count,
        "clones_with_ports":               len(clones_with_ports_set),
        "systems_with_parent_clone_dupes": systems_with_parent_clone_port_dupes,
        "audio": {
            "machines_reporting_channels": audio_total_with_channels,
            "channel_speaker_mismatches":  audio_channel_speaker_mismatch,
            "machines_requiring_samples":  audio_samples_required_count,
        },
        "overrides": overrides_stats,
    }

    # Finalise and save
    stamp_doc["created_utc"]   = finished_utc
    stamp_doc["inputs_detail"] = inputs_detail
    stamp_doc["outputs"]       = outputs
    stamp_doc["stats"]         = stats

    save_stamp(stamp_path, stamp_doc)

    log.info(
        f"Transformer completed in {duration:.2f}s "
        f"(eligible_parents={len(eligible_parents)}, included={len(out_map)})"
    )
    return bool(ok_out and ok_sum)
