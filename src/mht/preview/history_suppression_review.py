"""Read-only per-machine suppression evidence from the History summary.

A suppression is a recorded processing action, not necessarily an anomaly.
"""
from __future__ import annotations

from typing import Any

MAX_LINES = 30


def _map(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def build_machine_suppression_review(summary: dict, machine: str) -> dict:
    """Return source-backed lines and sections for an individual machine."""
    result = {"has_evidence": False, "line_count": 0, "lines": [],
              "lines_omitted": 0, "fully_suppressed": []}
    if not isinstance(summary, dict) or not isinstance(machine, str):
        return result

    recorded = _map(_map(summary.get("suppressions")).get("by_system")).get(machine)
    if isinstance(recorded, list):
        lines = [dict(section=item["section"], rule=item["rule"], line=item["line"])
                 for item in recorded
                 if isinstance(item, dict)
                 and all(isinstance(item.get(key), str) for key in ("section", "rule", "line"))]
        result["line_count"] = len(lines)
        result["lines"] = lines[:MAX_LINES]
        result["lines_omitted"] = max(0, len(lines) - MAX_LINES)

    fully = _map(summary.get("fully_suppressed_sections"))
    result["fully_suppressed"] = sorted(
        section for section, systems in fully.items()
        if isinstance(section, str) and isinstance(systems, list) and machine in systems
    )
    result["has_evidence"] = bool(result["line_count"] or result["fully_suppressed"])
    return result
