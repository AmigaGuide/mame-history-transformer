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

    return result
