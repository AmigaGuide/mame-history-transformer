"""
Summary shaping utilities and the MAME summary builder.

Includes:
- bucket_key_int(): stable key for optional ints ('unknown' vs 'N').
- sorted_* helpers: produce deterministic distributions with 'unknown' last.
- build_mame_summary(): constructs the totals/QA summary document used by the
  CLI validator and provenance outputs.
"""

from __future__ import annotations
from typing import Dict, Any, List, Set
import re
from collections import Counter

from mht.utils.versions import SCHEMA_IDS, schema_version, tool_version
from mht.utils.headers import build_summary_header
# Optional: if your repo already has a standard header helper, we’ll prefer it.
try:
    from mht.utils.headers import make_standard_header as _make_standard_header  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    _make_standard_header = None  # fallback below


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
