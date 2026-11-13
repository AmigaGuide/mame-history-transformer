"""Read-only, on-demand Preview adapter for the existing MHT release comparator.

Do not duplicate comparison logic here. A release folder is selectable only
when the three required, generated audit inputs exist.
"""
from __future__ import annotations

from typing import Any

from mht.audit.combined_diff import compare_release_content
from mht.utils.paths import (
    exotica_pages_path,
    exotica_wiki_path,
    gh_system_trivia_path,
    list_release_versions,
)


def available_releases() -> list[str]:
    """Find complete, numeric release datasets without modifying them."""
    result = []
    for release in list_release_versions():
        if not isinstance(release, str) or not (release.isascii() and release.isdecimal()):
            continue
        files = (exotica_wiki_path(release), exotica_pages_path(release),
                 gh_system_trivia_path(release))
        if all(path.is_file() for path in files):
            result.append(release)
    return sorted(set(result), key=lambda s: (int(s), s))


def _number(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _top_regions(value: Any, *, limit: int = 12) -> dict:
    rows = [{"name": str(k), "count": v} for k, v in (value if isinstance(value, dict) else {}).items()
            if _number(v) is not None]
    rows.sort(key=lambda row: (-row["count"], row["name"].casefold()))
    return {"rows": rows[:limit], "total": len(rows)}


def overview_context(*, active_release: str, before: str | None,
                     after: str | None, selected: bool = False) -> dict:
    """Prepare a compact view of two versions. Never execute a pipeline stage."""
    available = available_releases()
    if not selected:
        after = active_release if active_release in available else (available[-1] if available else None)
        predecessors = [v for v in available if after is not None and int(v) < int(after)]
        before = predecessors[-1] if predecessors else None

    context = {"available": available, "before": before, "after": after,
               "report": None, "error": None, "renamed": [], "renamed_total": 0,
               "regions": {"rows": [], "total": 0}, "affected_records": {}, "modified_records": {}}
    if not available or len(available) < 2:
        context["error"] = "At least two complete release datasets are required for comparison."
        return context
    if before is None or after is None:
        context["error"] = "Select two available releases to compare."
        return context
    if before not in available or after not in available:
        context["error"] = "One or both selected releases lack complete comparison datasets."
        return context
    if int(before) >= int(after):
        context["error"] = "The earlier release must precede the later release."
        return context

    try:
        report = compare_release_content(before, after)
    except (ValueError, OSError) as exc:
        context["error"] = str(exc)
        return context
    counts = report.get("counts") if isinstance(report, dict) else None
    if not isinstance(counts, dict):
        context["error"] = "The comparator did not return valid summary counts."
        return context
    context["report"] = {"counts": {k: _number(counts.get(k)) for k in (
                              "affected_machines", "modified", "trivia_changed_machines",
                              "added", "withdrawn", "unchanged", "wiki_affected_machines",
                              "changed_in_both", "trivia_only_machines",
                              "changed_trivia_sections", "page_name_changes")},
                          "scope": report.get("scope")}
    renamed = report.get("renamed") if isinstance(report.get("renamed"), list) else []
    context["renamed_total"] = len(renamed)
    context["renamed"] = [
        {"machine": x["machine"], "before": x["before"], "after": x["after"]}
        for x in renamed if isinstance(x, dict) and all(isinstance(x.get(k), str)
                                                        for k in ("machine", "before", "after"))
    ][:12]
    context["regions"] = _top_regions(report.get("affected_region_counts"))
    # Preserve comparator records for the independent read-only browsing selector.
    context["affected_records"] = report.get("affected") if isinstance(report.get("affected"), dict) else {}
    context["modified_records"] = report.get("modified") if isinstance(report.get("modified"), dict) else {}
    return context
