"""Compact, schema-backed presentation of Gaming History summary findings.

No source summary is modified. Counts are reported only when explicitly present.
"""
from __future__ import annotations

from typing import Any

SAMPLE_LIMIT = 5


def _map(obj: Any) -> dict:
    return obj if isinstance(obj, dict) else {}


def _count(obj: Any) -> int | None:
    return obj if type(obj) is int and obj >= 0 else None


def _preview(items: Any, limit: int = SAMPLE_LIMIT) -> list[str]:
    """Return names, not dictionary/list representations."""
    if isinstance(items, dict):
        values = list(items.keys())
    elif isinstance(items, (list, tuple)):
        values = items
    else:
        return []
    return [str(v) for v in values[:limit] if isinstance(v, (str, int)) and not isinstance(v, bool)]


def _display_name(name: str) -> str:
    return str(name).replace("_", " ").strip().capitalize()


def _ranked_group(mapping: Any, *, count_key: str, list_key: str, limit: int = 12) -> dict:
    entries = []
    for name, item in _map(mapping).items():
        entry = _map(item)
        count = _count(entry.get(count_key))
        if count is None:
            continue
        entries.append({"name": str(name), "count": count, "examples": _preview(entry.get(list_key))})
    entries.sort(key=lambda e: (-e["count"], e["name"].casefold()))
    return {"rows": entries[:limit], "total_groups": len(entries), "shown_groups": min(limit, len(entries))}


def build_history_report(summary: dict) -> dict:
    """Translate the existing GH schema into bounded, readable HTML sections."""
    totals = _map(summary.get("totals"))
    metrics = []
    for key, label in (
        ("systems_total", "Systems"), ("software_total", "Software entries"),
        ("systems_with_ports", "Systems with PORTS"),
        ("systems_with_aliases", "Systems with aliases"),
        ("port_lines_parsed", "PORTS lines parsed"),
    ):
        value = _count(totals.get(key))
        if value is not None:
            metrics.append({"label": label, "count": value})

    found = _map(summary.get("found"))
    platforms = _ranked_group(_map(found.get("platforms_found")).get("by_platform"),
                              count_key="systems_count", list_key="systems")
    publishers = _ranked_group(_map(found.get("publishers_found")).get("by_publisher"),
                               count_key="systems_count", list_key="systems")
    blocks = _map(_map(found.get("blocks")).get("by_type"))
    block_rows = [{"name": str(k), "count": v} for k, v in blocks.items() if _count(v) is not None]
    block_rows.sort(key=lambda e: (-e["count"], e["name"].casefold()))

    findings = []
    def add_findings(section_name: str, collection: Any, *, prefix: str):
        for key, value in _map(collection).items():
            if not isinstance(value, dict):
                continue
            count = _count(value.get("count"))
            affected = _count(value.get("systems_affected"))
            examples = _preview(value.get("by_system"))
            if not examples:
                examples = _preview(value.get("items"))
            if (count is None or count == 0) and (
                affected is None or affected == 0
            ):
                continue
            if count == 0 and (affected is None or affected == 0):
                continue
            findings.append({
                "label": _display_name(key),
                "category": section_name,
                "count": count,
                "systems_affected": affected,
                "examples": examples,
                "path": f"{prefix}.{key}",
            })

    add_findings("Source observations", summary.get("anomalies"), prefix="anomalies")
    add_findings("Residue", summary.get("residue_flags"), prefix="residue_flags")
    headings = _map(summary.get("headings_qc"))
    unmapped = _map(headings.get("unmapped_headings"))
    if unmapped:
        # Number of distinct headings, not automatically number of systems.
        findings.append({
            "label": "Unmapped headings", "category": "Heading review",
            "count": len(unmapped), "systems_affected": None,
            "examples": _preview(unmapped), "path": "headings_qc.unmapped_headings",
        })
    near = _map(headings.get("near_miss_banners"))
    if _count(near.get("systems_affected")):
        findings.append({
            "label": "Near-miss PORTS banners", "category": "Heading review",
            "count": None, "systems_affected": _count(near.get("systems_affected")),
            "examples": _preview(near.get("by_system")),
            "path": "headings_qc.near_miss_banners",
        })

    return {
        "metrics": metrics,
        "platforms": platforms,
        "publishers": publishers,
        "blocks": block_rows[:12],
        "blocks_total_types": len(block_rows),
        "findings": findings,
        "sample_limit": SAMPLE_LIMIT,
    }
