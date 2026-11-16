"""Source-backed structural observations for an individual GH machine.

These summary observations are not individual audit findings or verified errors.
No source archives or stage artefacts are read or changed here.
"""
from __future__ import annotations

from typing import Any

MAX_BANNER_LINES = 12


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def build_machine_structural_observations(summary: dict, machine: str) -> list[dict]:
    """Present only structural evidence explicitly recorded for *machine*.

    PORTS evidence is capped upstream at 140 characters. Near-miss banners
    are retained as raw lines, with only display count bounded here.
    """
    if not isinstance(summary, dict) or not isinstance(machine, str):
        return []

    result: list[dict] = []
    anomalies = _mapping(summary.get("anomalies"))
    ports = _mapping(_mapping(anomalies.get("ports_missing_subheadings")).get("by_system"))
    if machine in ports and isinstance(ports[machine], str):
        excerpt = ports[machine]
        result.append({
            "label": "PORTS without category subheadings",
            "description": (
                "The PORTS section did not contain recognised category subheadings. "
                "This can be valid source formatting; it is not necessarily an error."
            ),
            "items": [excerpt] if excerpt else [],
            "source_label": "Recorded source excerpt (up to 140 characters)",
            "path": "anomalies.ports_missing_subheadings.by_system",
            "omitted": 0,
        })

    headings = _mapping(summary.get("headings_qc"))
    by_system = _mapping(_mapping(headings.get("near_miss_banners")).get("by_system"))
    raw_lines = by_system.get(machine)
    if isinstance(raw_lines, list):
        lines = [item for item in raw_lines if isinstance(item, str) and item.strip()]
        if lines:
            result.append({
                "label": "Near-miss section banners",
                "description": (
                    "These source lines resemble section headings but did not match "
                    "the expected banner pattern. They remain review observations, "
                    "not confirmed source or parser defects."
                ),
                "items": lines[:MAX_BANNER_LINES],
                "source_label": "Recorded original GH lines",
                "path": "headings_qc.near_miss_banners.by_system",
                "omitted": max(0, len(lines) - MAX_BANNER_LINES),
            })

    # PORTS lines whose platform could not be identified. The summary retains
    # only bounded examples, so never present these as an exhaustive source list.
    null_ports = _mapping(anomalies.get("null_platform_ports"))
    by_machine = _mapping(null_ports.get("by_system"))
    line_examples = _mapping(null_ports.get("by_system_lines"))
    recorded_count = by_machine.get(machine)
    if type(recorded_count) is int and recorded_count > 0:
        examples = line_examples.get(machine)
        examples = [line for line in examples if isinstance(line, str)] if isinstance(examples, list) else []
        result.append({
            "label": "PORTS entries without an identified platform",
            "description": (
                "The parser recorded PORTS entries without an identified platform. "
                "This can reflect unusual source formatting or a parser limitation. "
                "The source summary retains only a limited sample."
            ),
            "items": examples[:MAX_BANNER_LINES],
            "source_label": f"Recorded source examples ({recorded_count} occurrence(s) for this machine)",
            "path": "anomalies.null_platform_ports.by_system_lines",
            "omitted": max(0, len(examples) - MAX_BANNER_LINES),
        })

    # An unmapped heading is stored as a normalised label with a list of
    # affected systems, not necessarily the original source line.
    unmapped = _mapping(headings.get("unmapped_headings"))
    heading_labels = sorted(
        label for label, details in unmapped.items()
        if isinstance(label, str) and isinstance(details, dict)
        and isinstance(details.get("systems"), list)
        and machine in details["systems"]
    )
    if heading_labels:
        result.append({
            "label": "Unmapped section headings",
            "description": (
                "These normalised GH headings were not mapped to a standard section. "
                "They may be intentional source headings or candidates for parser review. "
                "The summary does not retain the original heading line here."
            ),
            "items": heading_labels[:MAX_BANNER_LINES],
            "source_label": "Recorded normalised heading labels (not verbatim source lines)",
            "path": "headings_qc.unmapped_headings",
            "omitted": max(0, len(heading_labels) - MAX_BANNER_LINES),
        })


    # Category names are retained with affected machine memberships; they are
    # not verbatim source lines and need not constitute errors.
    unexpected = _mapping(anomalies.get("unexpected_platform_categories"))
    category_map = _mapping(unexpected.get("by_category"))
    categories = sorted(
        category for category, entry in category_map.items()
        if isinstance(category, str)
        and isinstance(entry, dict)
        and isinstance(entry.get("systems"), list)
        and machine in entry["systems"]
    )
    if categories:
        result.append({
            "label": "Unexpected PORTS category names",
            "description": (
                "These category names were not among the parser's expected PORTS "
                "categories. They may be legitimate source vocabulary; "
                "the summary stores labels rather than original source lines."
            ),
            "items": categories[:MAX_BANNER_LINES],
            "source_label": "Recorded category labels (not verbatim source lines)",
            "path": "anomalies.unexpected_platform_categories.by_category",
            "omitted": max(0, len(categories) - MAX_BANNER_LINES),
        })

    # Per-machine platform banner frequencies are observations, not faults.
    banners_by_machine = _mapping(_mapping(anomalies.get("platform_banners")).get("by_system"))
    banner_entry = _mapping(banners_by_machine.get(machine))
    banner_counts = _mapping(banner_entry.get("banners"))
    banner_lines = [
        f"{name} ({count} occurrence(s))"
        for name, count in sorted(banner_counts.items(), key=lambda kv: str(kv[0]).casefold())
        if isinstance(name, str) and type(count) is int and count >= 0
    ]
    if banner_lines:
        result.append({
            "label": "PORTS platform banners",
            "description": (
                "Banners and their recorded frequencies in this machine's PORTS "
                "section. Their presence is not necessarily a formatting defect."
            ),
            "items": banner_lines[:MAX_BANNER_LINES],
            "source_label": "Recorded banner labels and occurrence counts",
            "path": "anomalies.platform_banners.by_system",
            "omitted": max(0, len(banner_lines) - MAX_BANNER_LINES),
        })

    # The residue flag records membership only, not a reason or source line.
    residue = _mapping(summary.get("residue_flags"))
    residual_members = _mapping(residue.get("systems_with_residue")).get("items")
    if isinstance(residual_members, list) and machine in residual_members:
        result.append({
            "label": "Recorded residue flag",
            "description": (
                "The History parser flagged this machine as having residue. "
                "This summary field does not specify the cause or retain source text."
            ),
            "items": [],
            "source_label": "No per-machine residue details retained in this field",
            "path": "residue_flags.systems_with_residue.items",
            "omitted": 0,
        })

    return result
