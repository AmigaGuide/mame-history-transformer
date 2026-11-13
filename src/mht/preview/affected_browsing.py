"""Read-only browsing of machine changes returned by the combined release comparator.

This is a presentation selector, not a comparison engine. The ``affected``
records in the combined report remain authoritative.
"""
from __future__ import annotations

from typing import Any, Collection

PAGE_SIZE = 50
STATUSES = frozenset({"all", "added", "withdrawn", "modified", "renamed"})
CHANGES = frozenset({"all", "wiki", "trivia", "both", "trivia-only"})


def _page(value: Any) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError, OverflowError):
        return 1


def select_affected_machines(
    affected: Any, *, preview_machines: Collection[str] = (),
    query: str = "", status: str = "all", change: str = "all", page: Any = 1,
) -> dict:
    """Filter/paginate already-compared machines; never recompute diff counts.

    A Preview link is available only if the selected machine is in the active
    Preview catalogue, independently of its publication status in either release.
    """
    query = query.strip() if isinstance(query, str) else ""
    status = status if status in STATUSES else "all"
    change = change if change in CHANGES else "all"
    machine_set = set(preview_machines)
    matches: list[dict] = []
    records = affected if isinstance(affected, dict) else {}
    term = query.casefold()

    for machine, record in records.items():
        if not isinstance(machine, str) or not isinstance(record, dict):
            continue
        state = record.get("status")
        if state not in ("added", "withdrawn", "modified"):
            continue
        before = record.get("page_before")
        after = record.get("page_after")
        before = before if isinstance(before, str) else None
        after = after if isinstance(after, str) else None
        renamed = before is not None and after is not None and before != after
        wiki_regions = record.get("wiki_regions")
        wiki_regions = [v for v in wiki_regions if isinstance(v, str)] if isinstance(wiki_regions, list) else []
        trivia_sections = record.get("trivia_sections")
        trivia_sections = [v for v in trivia_sections if isinstance(v, str)] if isinstance(trivia_sections, list) else []
        # Additions and withdrawals count as Wiki-related even without a changed-region list.
        has_wiki = state in ("added", "withdrawn") or bool(wiki_regions) or renamed
        has_trivia = bool(trivia_sections)
        if status == "renamed":
            if not renamed:
                continue
        elif status != "all" and state != status:
            continue
        if change == "wiki" and not has_wiki:
            continue
        if change == "trivia" and not has_trivia:
            continue
        if change == "both" and not (has_wiki and has_trivia):
            continue
        if change == "trivia-only" and (has_wiki or not has_trivia):
            continue
        if term and not any(term in value.casefold() for value in (machine, before or "", after or "")):
            continue
        matches.append({
            "machine": machine,
            "status": state,
            "renamed": renamed,
            "page_before": before,
            "page_after": after,
            "wiki_regions": wiki_regions,
            "trivia_sections": trivia_sections,
            "has_wiki": has_wiki,
            "has_trivia": has_trivia,
            "preview_available": machine in machine_set,
        })

    matches.sort(key=lambda row: (row["machine"].casefold(), row["machine"]))
    total = len(matches)
    page_count = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    number = min(_page(page), page_count)
    start = (number - 1) * PAGE_SIZE
    return {
        "rows": matches[start:start + PAGE_SIZE],
        "total": total,
        "page": number,
        "page_count": page_count,
        "page_size": PAGE_SIZE,
        "query": query,
        "status": status,
        "change": change,
    }
