"""
Summary shaping utilities and the MAME summary builder.

Includes:
- bucket_key_int(): stable key for optional ints ('unknown' vs 'N').
- sorted_* helpers: produce deterministic distributions with 'unknown' last.
- build_mame_summary(): constructs the totals/QA summary document used by the
  CLI validator and provenance outputs.
"""

from __future__ import annotations
from typing import Dict, Any, List, Set, Optional, Tuple, Iterable
import re
from collections import Counter

from mht.utils.versions import SCHEMA_IDS, schema_version, tool_version
from mht.utils.headers import build_summary_header
# Optional: if your repo already has a standard header helper, we’ll prefer it.
try:
    from mht.utils.headers import make_standard_header as _make_standard_header  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    _make_standard_header = None  # fallback below
from mht.utils.io import read_json


_VERSION_CORE_RX = re.compile(r"\d+(?:\.\d+)+")


def build_transform_header(
    *,
    versions: Dict[str, Any],
    started_utc: str,
    finished_utc: str,
    duration_seconds: float,
) -> Dict[str, Any]:
    """
    Build the standard header block for transform_summary.json.

    Adds transformer_version automatically. Uses your centralised schema ids/versions.
    """
    schema_id = SCHEMA_IDS["transform"]
    schema_ver = schema_version(schema_id)

    # ensure transformer version is present
    v = dict(versions or {})
    v.setdefault("transformer_version", tool_version("transformer"))

    if _make_standard_header:
        # Prefer the shared header helper if available.
        return _make_standard_header(
            schema_id=schema_id,
            schema_version=schema_ver,
            versions=v,
            started_utc=started_utc,
            finished_utc=finished_utc,
            duration=duration_seconds,
        )

    # Minimal inline fallback (keeps current shape)
    return {
        "schema_id": schema_id,
        "schema_version": schema_ver,
        "generated_at": finished_utc,
        "started_utc": started_utc,
        "finished_utc": finished_utc,
        "duration_seconds": duration_seconds,
        "versions": v,
    }

def _count_parents_with_clones(out_map: Dict[str, Any]) -> int:
    """How many included parents have at least one clone listed in mame_titles."""
    n = 0
    for rec in (out_map or {}).values():
        titles = rec.get("mame_titles") or []
        if any((t.get("role") or "").strip().lower() == "clone" for t in titles):
            n += 1
    return n

def _total_clones_linked(out_map: Dict[str, Any]) -> int:
    """Total number of clone rows listed across all included parents."""
    total = 0
    for rec in (out_map or {}).values():
        titles = rec.get("mame_titles") or []
        total += sum(1 for t in titles if (t.get("role") or "").strip().lower() == "clone")
    return total

def build_transform_summary(
    *,
    header: Dict[str, Any],
    inputs: Dict[str, str],
    outputs: Dict[str, str],

    # High-level sets/maps
    out_map: Dict[str, Any],                    # included parents map
    parents_map: Dict[str, List[str]],          # parent->clones from parent_index

    # Top-level counts for MAME universe
    mame_total: int,
    parents_total: int,
    clones_total: int,
    eligible_parents: Set[str],

    # Media / audio telemetry (already computed in transformer)
    media_label_counts: Dict[str, int],
    parents_with_any_media: int,
    audio: Dict[str, Any],   # {machines_reporting_channels, channel_speaker_mismatches, mismatch_examples, machines_requiring_samples}

    # Ports block (already computed in transformer)
    ports: Dict[str, Any],

    # Optional diagnostics
    excluded_parents_by_reason: Dict[str, int] | None = None,
    included_flags: Dict[str, int] | None = None,
    title_anomalies: Dict[str, List[Dict[str, Any]]] | None = None,
    title_overrides: Dict[str, Any] | None = None,
    errors: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """
    Frame the final transform summary document from precomputed blocks.
    This function is intentionally light on logic: it only derives a few
    safe, deterministic counters from out_map.
    """

    # Derived counts from included set
    final_included = len(out_map)
    parents_with_clones = _count_parents_with_clones(out_map)
    total_clones_linked = _total_clones_linked(out_map)

    counts_block = {
        "mame_total": mame_total,
        "parents_total": parents_total,
        "clones_total": clones_total,
        "eligible_parents": len(eligible_parents),
        "final_included": final_included,
        "parents_with_clones": parents_with_clones,
        "total_clones_linked": total_clones_linked,
        "parents_without_clones": max(0, len(eligible_parents) - parents_with_clones),
        "parents_with_any_media": parents_with_any_media,
        "media_label_counts": dict(sorted((media_label_counts or {}).items(), key=lambda kv: kv[0].casefold())),
        "audio": {
            "machines_reporting_channels": int((audio or {}).get("machines_reporting_channels", 0)),
            "channel_speaker_mismatches": int((audio or {}).get("channel_speaker_mismatches", 0)),
            "mismatch_examples": (audio or {}).get("mismatch_examples", []),
            "machines_requiring_samples": int((audio or {}).get("machines_requiring_samples", 0)),
        },
    }

    summary: Dict[str, Any] = {
        "header": header,
        # Legacy mirror fields retained one cycle (your transformer does this today)
        "transformer_schema": header.get("schema_version"),
        "started_utc": header.get("started_utc"),
        "finished_utc": header.get("finished_utc"),
        "duration_seconds": header.get("duration_seconds"),
        "inputs": inputs or {},
        "outputs": outputs or {},
        # Simple mirror of versions (kept for backward-compat in tests)
        "versions": header.get("versions", {}),
        "counts": counts_block,
        "excluded_parents_by_reason": excluded_parents_by_reason or {},
        "included_flags": included_flags or {},
        "title_anomaly_counts": {k: len(v or []) for k, v in (title_anomalies or {}).items()} if title_anomalies else {},
        "title_anomalies": title_anomalies or {},
        "title_overrides": title_overrides or {"stats": {"configured": 0, "eligible": 0, "applied": 0}, "applied": []},
        "ports": ports or {},
        "notes": {
            # Keep your current explanatory notes; transformer can still override/extend this dict if desired.
            "ports_attached": True,
            "export_scope": (
                "Parents are exported only if INI says Arcade/Game AND the parent or any clone has ≥1 valid GH port row (platform present)."
            ),
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
            # The ignored devices “top N” list is curated in transformer; if you
            # still compute it there, you can attach under notes.ignored_media_devices.
        },
        "errors": errors or [],
    }

    return summary

def version_core(s: str | None) -> str | None:
    """
    Extract the dotted version core from a string, e.g.
    'MAME 0.263 (mame0263)' -> '0.263'. Returns None if not found.
    """
    if not s:
        return None
    m = _VERSION_CORE_RX.search(s)
    return m.group(0) if m else None

def bucket_key_int(v: int | None) -> str:
    """
    Convert an optional int to a stable counter/distribution key.
    Returns the numeric string for ints, otherwise 'unknown'.
    """
    return str(v) if v is not None else "unknown"

def sorted_numeric_keys_with_unknown_last(counter: Dict[str, int]) -> Dict[str, int]:
    """
    Return a dict with numeric-string keys sorted ascending,
    any non-numeric keys (except 'unknown') merged into 'other',
    and 'unknown' (if present) appended last.
    """
    numeric = []
    unknown = None
    other = 0
    for k, v in counter.items():
        if k == "unknown":
            unknown = v
        elif k.isdigit():
            numeric.append((int(k), v))
        else:
            other += v
    numeric.sort(key=lambda t: t[0])
    out: Dict[str, int] = {str(k): v for k, v in numeric}
    if other:
        out["other"] = other
    if unknown is not None:
        out["unknown"] = unknown
    return out

def sorted_alpha_with_unknown_last(counter: Dict[str, int]) -> Dict[str, int]:
    """
    Return a dict with keys sorted A–Z case-insensitively,
    placing 'unknown' (if present) at the end.
    """
    items = [(k, v) for k, v in counter.items() if k != "unknown"]
    items.sort(key=lambda kv: kv[0].lower())
    out = {k: v for k, v in items}
    if "unknown" in counter:
        out["unknown"] = counter["unknown"]
    return out

def sort_numeric_str(counter: Dict[str, int]) -> Dict[str, int]:
    """
    Return a new dict with only numeric-string keys sorted ascending.
    Caller can append 'unknown' manually if needed.
    """
    items = [(int(k), v) for k, v in counter.items() if k.isdigit()]
    items.sort(key=lambda t: t[0])
    return {str(k): v for k, v in items}

def build_mame_summary(
    *,
    total_machines: int,
    total_parents: int,
    total_clones: int,
    total_isbios: int,
    total_isdevice: int,
    total_ismechanical: int,
    total_requires_samples: int,
    years_ctr: Counter,
    manuf_ctr: Counter,
    players_ctr: Counter,
    control_type_overall_ctr: Counter,
    control_ways_overall_ctr: Counter,
    control_ways2_overall_ctr: Counter,
    control_ways3_overall_ctr: Counter,
    control_buttons_overall_ctr: Counter,
    control_reqbuttons_overall_ctr: Counter,
    cpus_per_machine_ctr: Counter,
    sound_devices_per_machine_ctr: Counter,
    displays_per_machine_ctr: Counter,
    display_types_overall_ctr: Counter,
    display_tags_overall_ctr: Counter,
    sound_channels_per_machine_ctr: Counter,
    speakers_per_machine_ctr: Counter,
    disk_regions_overall_ctr: Counter,
    disk_media_platforms_per_machine_ctr: Counter,
    disk_media_examples: Dict[str, List[str]],
    dropped_displays_total: int,
    dropped_displays_examples: List[Dict[str, Any]],
    mame_build: str | None,
    mame_mameconfig: str | None,
) -> Dict[str, Any]:
    """Build the MAME parse summary document. Shape identical to previous inline version."""

    def _numdist(counter: Counter) -> Dict[str, int]:
        dist = sort_numeric_str(dict(counter))
        if "unknown" in counter:
            dist["unknown"] = counter["unknown"]
        return dist

    years_dist = sorted_numeric_keys_with_unknown_last(dict(years_ctr))
    manuf_dist = sorted_alpha_with_unknown_last(dict(manuf_ctr))
    display_types_overall_dist = sorted_alpha_with_unknown_last(dict(display_types_overall_ctr))
    display_tags_overall_dist = sorted_alpha_with_unknown_last(dict(display_tags_overall_ctr))

    players_dist = _numdist(players_ctr)
    cpus_dist = _numdist(cpus_per_machine_ctr)
    sounds_dist = _numdist(sound_devices_per_machine_ctr)
    displays_dist = _numdist(displays_per_machine_ctr)
    speakers_dist = _numdist(speakers_per_machine_ctr)
    sound_channels_dist = _numdist(sound_channels_per_machine_ctr)

    disk_regions_overall_dist = sorted_alpha_with_unknown_last(dict(disk_regions_overall_ctr))

    years_sum = sum(years_dist.values())
    manufacturers_sum = sum(manuf_dist.values())
    players_sum = sum(players_dist.values())
    cpus_sum = sum(cpus_dist.values())
    sounds_sum = sum(sounds_dist.values())
    displays_sum = sum(displays_dist.values())
    speakers_sum = sum(speakers_dist.values())
    sound_channels_sum = sum(sound_channels_dist.values())
    display_types_overall_sum = sum(display_types_overall_dist.values())
    display_tags_overall_sum = sum(display_tags_overall_dist.values())
    disk_regions_overall_sum = sum(disk_regions_overall_dist.values())

    mame_build_str = mame_build
    mame_xml_version = (
        mame_build_str.split(" ", 1)[0]
        if isinstance(mame_build_str, str) and mame_build_str.strip()
        else None
    )
    versions_block: Dict[str, Any] = {}
    if mame_xml_version:
        versions_block["mame_xml_version"] = mame_xml_version
    if mame_build_str:
        versions_block["mame_build"] = mame_build_str
    if mame_mameconfig is not None:
        versions_block["mameconfig"] = mame_mameconfig

    header = build_summary_header(
        schema_id=SCHEMA_IDS["mame"],
        schema_version=schema_version(SCHEMA_IDS["mame"]),
        versions={
            **versions_block,
            "mame_parser_version": tool_version("mame_parser"),
        },
    )

    doc: Dict[str, Any] = {
        "header": header,
        "totals": {
            "total_machines": total_machines,
            "total_parents": total_parents,
            "total_clones": total_clones,
            "total_isbios": total_isbios,
            "total_isdevice": total_isdevice,
            "total_ismechanical": total_ismechanical,
            "total_requires_samples": total_requires_samples,
            "years": {
                "unique": len([k for k in years_dist.keys() if k != "unknown"]),
                "distribution": years_dist,
                "sum": years_sum,
            },
            "manufacturers": {
                "unique": len([k for k in manuf_dist.keys() if k != "unknown"]),
                "distribution": manuf_dist,
                "sum": manufacturers_sum,
            },
            "players": {"distribution": players_dist, "sum": players_sum},
            "controls": {
                "types_overall": {
                    "distribution": sorted_alpha_with_unknown_last(dict(control_type_overall_ctr)),
                    "sum": sum(dict(control_type_overall_ctr).values()),
                },
                "ways_overall": {
                    "distribution": sorted_alpha_with_unknown_last(dict(control_ways_overall_ctr)),
                    "sum": sum(dict(control_ways_overall_ctr).values()),
                },
                "ways2_overall": {
                    "distribution": sorted_alpha_with_unknown_last(dict(control_ways2_overall_ctr)),
                    "sum": sum(dict(control_ways2_overall_ctr).values()),
                },
                "ways3_overall": {
                    "distribution": sorted_alpha_with_unknown_last(dict(control_ways3_overall_ctr)),
                    "sum": sum(dict(control_ways3_overall_ctr).values()),
                },
                "buttons_overall": {
                    "distribution": _numdist(control_buttons_overall_ctr),
                    "sum": sum(control_buttons_overall_ctr.values()),
                },
                "reqbuttons_overall": {
                    "distribution": _numdist(control_reqbuttons_overall_ctr),
                    "sum": sum(control_reqbuttons_overall_ctr.values()),
                },
            },
            "cpus_per_machine": {"distribution": cpus_dist, "sum": cpus_sum},
            "sound_devices_per_machine": {"distribution": sounds_dist, "sum": sounds_sum},
            "displays_per_machine": {"distribution": displays_dist, "sum": displays_sum},
            "display_types_overall": {"distribution": display_types_overall_dist, "sum": display_types_overall_sum},
            "display_tags_overall": {"distribution": display_tags_overall_dist, "sum": display_tags_overall_sum},
            "sound_channels_per_machine": {"distribution": sound_channels_dist, "sum": sound_channels_sum},
            "speakers_per_machine": {"distribution": speakers_dist, "sum": speakers_sum},
            "disk_regions_overall": {"distribution": disk_regions_overall_dist, "sum": disk_regions_overall_sum},
            "disk_media_platforms_per_machine": {
                "distribution": sort_numeric_str(dict(disk_media_platforms_per_machine_ctr)) | (
                    {"unknown": disk_media_platforms_per_machine_ctr["unknown"]}
                    if "unknown" in disk_media_platforms_per_machine_ctr else {}
                ),
                "sum": sum(disk_media_platforms_per_machine_ctr.values()),
                "examples": disk_media_examples,
            },
            "invalid_displays_dropped": {
                "count": dropped_displays_total,
                "examples": dropped_displays_examples
            },
        },
    }

    # additive aliases + anomalies mirror (as before)
    totals = doc["totals"]
    if "total_is_bios" not in totals:
        totals["total_is_bios"] = totals["total_isbios"]
    if "total_is_device" not in totals:
        totals["total_is_device"] = totals["total_isdevice"]
    legacy_drop = totals.get("invalid_displays_dropped")
    if legacy_drop:
        doc.setdefault("anomalies", {}).setdefault("dropped_displays", legacy_drop)

    return doc

def update_counters(
    *,
    # per-machine inputs
    year_key: str,
    manufacturer_key: str,
    players_key: str,
    cpu_count: int,
    audio_count: int,
    display_count: int,
    sound_channels: Optional[int],
    speaker_ref_count: int,
    disk_regions_overall_add: Dict[str, int],
    disk_media_platforms_count: int,
    mame_name: str,
    # counters to mutate
    years_ctr: Counter,
    manuf_ctr: Counter,
    players_ctr: Counter,
    cpus_per_machine_ctr: Counter,
    sound_devices_per_machine_ctr: Counter,
    displays_per_machine_ctr: Counter,
    sound_channels_per_machine_ctr: Counter,
    speakers_per_machine_ctr: Counter,
    disk_regions_overall_ctr: Counter,
    disk_media_platforms_per_machine_ctr: Counter,
    disk_media_examples: Dict[str, list],
) -> None:
    """
    Mutate aggregate counters for one parsed machine. No return value.
    Mirrors the previous inline updates in mame_parser.
    """
    years_ctr[year_key] += 1
    manuf_ctr[manufacturer_key] += 1
    players_ctr[players_key] += 1

    cpus_per_machine_ctr[bucket_key_int(cpu_count)] += 1
    sound_devices_per_machine_ctr[bucket_key_int(audio_count)] += 1
    displays_per_machine_ctr[bucket_key_int(display_count)] += 1
    sound_channels_per_machine_ctr[bucket_key_int(sound_channels)] += 1
    speakers_per_machine_ctr[bucket_key_int(speaker_ref_count)] += 1

    # per-region overall counts (not deduped)
    for k, v in (disk_regions_overall_add or {}).items():
        disk_regions_overall_ctr[k] += v

    # disk platforms per machine + examples (cap handled by caller if needed)
    disk_media_platforms_per_machine_ctr[bucket_key_int(disk_media_platforms_count)] += 1
    examples = disk_media_examples.setdefault(str(disk_media_platforms_count), [])
    if len(examples) < 5:
        examples.append(mame_name)

def update_totals(
    total_machines: int,
    total_parents: int,
    total_clones: int,
    total_isbios: int,
    total_isdevice: int,
    total_ismechanical: int,
    total_requires_samples: int,
    *,
    cloneof: str | None,
    isbios: str,
    isdevice: str,
    ismechanical: str,
    requires_samples: bool,
) -> Tuple[int, int, int, int, int, int, int]:
    """
    Apply one machine's contributions to the running totals.

    - Increments total_machines by 1.
    - Classifies parent vs clone using 'cloneof'.
    - Adds to is* counts when string flags are 'yes'.
    - Adds to total_requires_samples when True.
    """
    total_machines += 1
    if cloneof:
        total_clones += 1
    else:
        total_parents += 1
    if isbios == "yes":
        total_isbios += 1
    if isdevice == "yes":
        total_isdevice += 1
    if ismechanical == "yes":
        total_ismechanical += 1
    if requires_samples:
        total_requires_samples += 1

    return (
        total_machines,
        total_parents,
        total_clones,
        total_isbios,
        total_isdevice,
        total_ismechanical,
        total_requires_samples,
    )

def apply_ports_results(
    *,
    parsing_state: Dict[str, Any],
    primary: str,
    entry_data: Dict[str, Any],
    overview: str | None,
    platform_counts: Dict[str, int] | None,
    platform_ports: Dict[str, Any] | None,
    port_lines: int,
    systems_with_ports: int,
    port_overview_count: int,
    total_port_lines_all: int,
) -> Tuple[int, int, int, Dict[str, Any]]:
    """
    Apply PORTS parsing results to counters/state and return updated tallies
    and entry_data (shape unchanged).
    """
    systems_with_ports += 1
    total_port_lines_all += port_lines

    if overview:
        entry_data["port_overview"] = overview
        parsing_state["systems_with_port_overview"][primary] = overview
        port_overview_count += 1

    if platform_ports:
        entry_data["ports"] = platform_ports

    if platform_counts:
        for cat, c in platform_counts.items():
            parsing_state["platform_categories_found"][cat] += c

    return systems_with_ports, port_overview_count, total_port_lines_all, entry_data

def update_history_totals(
    total_entries: int,
    systems_count: int,
    software_count: int,
    systems_with_aliases: int,
    *,
    kind: str,            # "systems" | "software" | "unknown"
    aliases: list[str],
) -> Tuple[int, int, int, int]:
    """
    Apply one entry's contributions to the running history totals.

    - Increments total_entries by 1.
    - Increments systems_count or software_count based on 'kind'.
    - Increments systems_with_aliases if aliases is non-empty (only meaningful for 'systems').
    """
    total_entries += 1
    if kind == "systems":
        systems_count += 1
        if aliases:
            systems_with_aliases += 1
    elif kind == "software":
        software_count += 1
    return total_entries, systems_count, software_count, systems_with_aliases

# --- Transform versions extraction (centralised) ---
def extract_stage_versions_for_transform(
    mame_summary_path,
    history_summary_path,
    ini_summary_path,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Read stage summaries and derive:
      - 'versions' for transform summary header
      - 'wiki_header_versions' for wiki/raw headers
    Returns (versions_dict, wiki_header_versions_dict).
    """

    def _get(d, *path, default=None):
        cur = d
        for k in path:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    mame_sum = read_json(mame_summary_path) or {}
    hist_sum = read_json(history_summary_path) or {}
    ini_sum  = read_json(ini_summary_path) or {}

    # Canonical (header-first), with legacy fallbacks
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

    # mame_xml core version for wiki header
    from mht.utils.summaries import version_core as _core  # already in this module
    mame_core = _get(mame_sum, "header", "versions", "mame_xml_version") or _core(mame_build_val)
    hist_version_raw = history_version_val

    # ini_versions map for wiki header (filename -> version string)
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

    return versions, wiki_header_versions

def build_selection_telemetry(
    out_map: Dict[str, Dict[str, Any]],
    eligible_parents: Iterable[str],
    excluded_parents_by_reason: Dict[str, int],
) -> Dict[str, Any]:
    """
    Compute high-level selection telemetry for transform_summary.
    Pure; no I/O.
    """
    eligible_parents_total = len(set(eligible_parents))
    included_parents_after_ports_gate = len(out_map)

    parents_with_own_ports = 0
    parents_included_via_clones_only = 0

    for rec in out_map.values():
        ports = rec.get("ports") or {}
        ps = ports.get("parent_source") or {}
        cats = ps.get("categories") if isinstance(ps, dict) else None
        if cats:
            parents_with_own_ports += 1
        else:
            parents_included_via_clones_only += 1

    return {
        "eligible_parents_total": eligible_parents_total,
        "included_parents_after_ports_gate": included_parents_after_ports_gate,
        "parents_with_own_ports": parents_with_own_ports,
        "parents_included_via_clones_only": parents_included_via_clones_only,
        "excluded_parents_by_reason": dict(excluded_parents_by_reason or {}),
    }

def build_displays_shape_telemetry(
    out_map: Dict[str, Dict[str, Any]],
) -> Dict[str, int]:
    """
    Count grouped screens by raster-like vs non-raster types for sanity checks.
    Pure; no I/O.
    """
    raster_lcd_with_dims_total = 0
    svg_vector_total = 0

    for rec in out_map.values():
        groups = (((rec.get("displays") or {}).get("groups")) or [])
        for g in groups:
            t = (g.get("type") or "").strip()
            c = int(g.get("count") or 0) or 1
            if t in ("Raster", "LCD"):
                # By contract, width/height exist for raster-like groups
                if "width" in g and "height" in g:
                    raster_lcd_with_dims_total += c
            elif t in ("SVG", "Vector"):
                # By contract, width/height absent for SVG/Vector
                svg_vector_total += c

    return {
        "raster_lcd_with_dims_total": raster_lcd_with_dims_total,
        "svg_vector_total": svg_vector_total,
    }
