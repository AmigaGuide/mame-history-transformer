from __future__ import annotations
from typing import Dict, Any, List, Set
import re

from mht.utils.versions import SCHEMA_IDS, schema_version, tool_version

_VERSION_CORE_RX = re.compile(r"\d+(?:\.\d+)+")

# Optional: if your repo already has a standard header helper, we’ll prefer it.
try:
    from mht.utils.headers import make_standard_header as _make_standard_header  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    _make_standard_header = None  # fallback below


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
