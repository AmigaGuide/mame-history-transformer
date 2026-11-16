"""Read-only review of machine-specific Transform publication deferrals."""
from __future__ import annotations

from typing import Any

PAGE_SIZE = 50


def _map(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _reasons(summary: Any) -> dict[str, str]:
    publication = _map(_map(summary).get("publication"))
    source = _map(publication.get("deferred_machine_reasons"))
    return {
        machine: reason for machine, reason in source.items()
        if isinstance(machine, str) and machine.strip()
        and isinstance(reason, str) and reason.strip()
    }


def machine_deferred_reason(summary: Any, machine: str) -> str | None:
    """Return exactly the stored reason; don't derive eligibility."""
    return _reasons(summary).get(machine)


def build_publication_review(
    summary: Any, *, preview_machines: Any, query: str = "",
    reason: str = "", page: str = "1",
) -> dict:
    """Filter and paginate the stored mapping without changing publication."""
    mapping = _reasons(summary)
    available = set(preview_machines) if isinstance(preview_machines, (list, tuple, set)) else set()
    query = query.strip()[:120] if isinstance(query, str) else ""
    reason = reason.strip()[:200] if isinstance(reason, str) else ""
    choices = sorted(set(mapping.values()), key=str.casefold)
    if reason not in choices:
        reason = ""
    rows = [
        {"machine": machine, "reason": explanation, "preview": machine in available}
        for machine, explanation in sorted(mapping.items(), key=lambda item: item[0].casefold())
        if (not query or query.casefold() in machine.casefold()
            or query.casefold() in explanation.casefold())
        and (not reason or explanation == reason)
    ]
    try:
        number = int(page)
    except (TypeError, ValueError):
        number = 1
    total_pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    number = min(max(1, number), total_pages)
    start = (number - 1) * PAGE_SIZE
    publication = _map(_map(summary).get("publication"))
    recorded_total = publication.get("deferred_parents")
    if type(recorded_total) is not int or recorded_total < 0:
        recorded_total = None
    return {
        "rows": rows[start:start + PAGE_SIZE],
        "total": len(rows),
        "all_records": len(mapping),
        "recorded_total": recorded_total,
        "q": query, "reason": reason, "reasons": choices,
        "page": number, "pages": total_pages, "page_size": PAGE_SIZE,
    }
