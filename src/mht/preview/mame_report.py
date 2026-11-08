"""Bounded, source-backed MAME parsing report for the Flask preview.

The report never modifies the summary, invents counts or expands a complete
machine distribution into HTML.  Missing information remains unavailable.
"""
from __future__ import annotations

from typing import Any

SAMPLE_LIMIT = 5
DISTRIBUTION_LIMIT = 12


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _examples(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:SAMPLE_LIMIT]:
        if not isinstance(item, dict):
            if isinstance(item, str):
                result.append({"machine": item, "detail": None})
            continue
        machine = item.get("machine")
        if not isinstance(machine, str) or not machine.strip():
            continue
        fields = []
        for key in ("type", "width", "height", "tag"):
            val = item.get(key)
            if isinstance(val, (str, int)) and not isinstance(val, bool) and str(val).strip():
                fields.append(f"{key}: {val}")
        result.append({"machine": machine, "detail": ", ".join(fields) or None})
    return result


def _distribution(label: str, field: str, container: Any) -> dict | None:
    data = _mapping(container)
    distribution = _mapping(data.get("distribution"))
    rows = [
        {"name": str(name), "count": count}
        for name, count in distribution.items()
        if _count(count) is not None
    ]
    if not rows:
        return None
    rows.sort(key=lambda row: (-row["count"], row["name"].casefold()))
    return {
        "label": label,
        "path": f"totals.{field}.distribution",
        "rows": rows[:DISTRIBUTION_LIMIT],
        "total_groups": len(rows),
        "shown_groups": min(len(rows), DISTRIBUTION_LIMIT),
    }


def build_mame_report(summary: dict) -> dict:
    """Build a concise HTML-ready view from recorded MAME summary values."""
    totals = _mapping(summary.get("totals"))
    versions = _mapping(_mapping(summary.get("header")).get("versions"))
    input_records = _mapping(summary.get("provenance")).get("inputs")
    source = next((r for r in input_records if isinstance(r, dict)), {}) if isinstance(input_records, list) else {}

    metrics = []
    for field, label in (
        ("total_machines", "Machines parsed"),
        ("total_parents", "Parents"),
        ("total_clones", "Clones"),
        ("total_isbios", "BIOS machines"),
        ("total_isdevice", "Device entries"),
        ("total_ismechanical", "Mechanical machines"),
        ("total_requires_samples", "Machines requiring samples"),
    ):
        value = _count(totals.get(field))
        if value is not None:
            metrics.append({"label": label, "value": value})

    distributions = []
    for label, field, container in (
        ("Manufacturers", "manufacturers", totals.get("manufacturers")),
        ("Years", "years", totals.get("years")),
        ("Players per machine", "players", totals.get("players")),
        ("Control types", "controls.types_overall", _mapping(totals.get("controls")).get("types_overall")),
        ("Buttons per machine", "controls.buttons_overall", _mapping(totals.get("controls")).get("buttons_overall")),
        ("CPUs per machine", "cpus_per_machine", totals.get("cpus_per_machine")),
        ("Displays per machine", "displays_per_machine", totals.get("displays_per_machine")),
        ("Display types", "display_types_overall", totals.get("display_types_overall")),
        ("Sound channels per machine", "sound_channels_per_machine", totals.get("sound_channels_per_machine")),
        ("Speakers per machine", "speakers_per_machine", totals.get("speakers_per_machine")),
        ("Disk media platforms per machine", "disk_media_platforms_per_machine", totals.get("disk_media_platforms_per_machine")),
    ):
        result = _distribution(label, field, container)
        if result:
            distributions.append(result)

    findings = []
    # Canonical MAME field: totals.invalid_displays_dropped; the anomaly mirror
    # contains identical data and must not become a second finding.
    dropped = _mapping(totals.get("invalid_displays_dropped"))
    if not dropped:
        dropped = _mapping(_mapping(summary.get("anomalies")).get("dropped_displays"))
    number = _count(dropped.get("count"))
    if number is not None and number > 0:
        findings.append({
            "label": "Invalid display records dropped",
            "count": number,
            "examples": _examples(dropped.get("examples")),
            "path": "totals.invalid_displays_dropped" if "invalid_displays_dropped" in totals else "anomalies.dropped_displays",
        })

    return {
        "versions": versions,
        "source": source,
        "metrics": metrics,
        "findings": findings,
        "distributions": distributions,
        "sample_limit": SAMPLE_LIMIT,
        "distribution_limit": DISTRIBUTION_LIMIT,
    }
