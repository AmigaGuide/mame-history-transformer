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

    return result
