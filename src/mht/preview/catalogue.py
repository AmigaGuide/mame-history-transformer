"""Read-only selection and pagination for the Flask preview catalogue."""
from __future__ import annotations

from typing import Any

from .preview_data import PreviewData

PAGE_SIZE = 50
VALID_STATUSES = frozenset({"all", "published", "trivia-only"})
VALID_TRIVIA = frozenset({"any", "yes", "no"})


def _page_number(raw: Any) -> int:
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(1, number)


def select_catalogue_page(
    preview_data: PreviewData,
    *,
    query: str = "",
    status: str = "all",
    trivia: str = "any",
    page: Any = 1,
) -> dict:
    """Filter in-memory records without changing source data or navigation order.

    ``trivia=yes`` means the machine is a key in gh_system_trivia.json,
    not necessarily that it has a non-empty classified block.
    """
    query = (query or "").strip()
    status = status if status in VALID_STATUSES else "all"
    trivia = trivia if trivia in VALID_TRIVIA else "any"
    match = query.casefold()

    rows = []
    for machine in preview_data.machine_order:
        published_rec = preview_data.wiki_games.get(machine)
        published = published_rec is not None
        has_gh_record = machine in preview_data.trivia_by_machine
        if status == "published" and not published:
            continue
        if status == "trivia-only" and published:
            continue
        if trivia == "yes" and not has_gh_record:
            continue
        if trivia == "no" and has_gh_record:
            continue

        wiki = published_rec or {}
        mame = preview_data.mame_machines.get(machine) or {}
        description = mame.get("description") or wiki.get("wiki_page_name") or machine
        if match and match not in machine.casefold() and match not in str(description).casefold():
            continue
        rows.append({
            "machine": machine,
            "description": description,
            "year": wiki.get("year") or mame.get("year"),
            "manufacturer": wiki.get("manufacturer") or mame.get("manufacturer"),
            "published": published,
            "has_gh_record": has_gh_record,
        })

    rows.sort(key=lambda item: item["machine"].casefold())
    count = len(rows)
    page_count = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
    number = min(_page_number(page), page_count)
    start = (number - 1) * PAGE_SIZE
    return {
        "query": query,
        "status": status,
        "trivia": trivia,
        "results": rows[start:start + PAGE_SIZE],
        "total_results": count,
        "page": number,
        "page_count": page_count,
        "page_size": PAGE_SIZE,
    }
