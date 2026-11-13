"""Presentation of a single machine's recorded cross-release differences.

The combined comparator determines membership and changed fields. This module
only reads their recorded values and formats bounded previews for the web UI.
"""
from __future__ import annotations

import json
from typing import Any

from mht.audit.release_diff import _load_release
from mht.audit.trivia_details import detail_for_machine


MAX_FIELD_CHARS = 1800


def _display(value: Any) -> str:
    if value is _ABSENT:
        return "Field not present"
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    if len(text) > MAX_FIELD_CHARS:
        return text[:MAX_FIELD_CHARS] + "\n... [display shortened; consult generated JSON for complete value]"
    return text


_ABSENT = object()


def build_machine_detail(*, before: str, after: str, machine: str,
                         affected: dict, modified: dict) -> dict:
    """Build details only for a machine already reported by the comparator.

    Does not independently determine changes, or inspect the live Wiki.
    """
    rec = affected.get(machine)
    if not isinstance(rec, dict):
        raise LookupError("Machine not reported as affected in this comparison.")
    status = rec.get("status")
    if status not in ("added", "withdrawn", "modified"):
        raise ValueError("Unexpected comparison status for machine.")
    wiki_regions = rec.get("wiki_regions")
    trivia_sections = rec.get("trivia_sections")
    wiki_regions = [x for x in wiki_regions if isinstance(x, str)] if isinstance(wiki_regions, list) else []
    trivia_sections = [x for x in trivia_sections if isinstance(x, str)] if isinstance(trivia_sections, list) else []
    page_before = rec.get("page_before")
    page_after = rec.get("page_after")
    page_before = page_before if isinstance(page_before, str) else None
    page_after = page_after if isinstance(page_after, str) else None
    mod = modified.get(machine) if isinstance(modified, dict) else None
    changed_fields = mod.get("changed_fields") if isinstance(mod, dict) else None
    changed_fields = [k for k in changed_fields if isinstance(k, str)] if isinstance(changed_fields, list) else []

    fields = []
    if status == "modified" and changed_fields:
        # Source records are read only after the comparator has identified fields.
        before_doc, _ = _load_release(before)
        after_doc, _ = _load_release(after)
        old = before_doc["games"].get(machine, {})
        new = after_doc["games"].get(machine, {})
        for field in sorted(set(changed_fields)):
            fields.append({"name": field,
                           "before": _display(old.get(field, _ABSENT)),
                           "after": _display(new.get(field, _ABSENT))})

    trivia_text = detail_for_machine(before, after, machine) if trivia_sections else ""
    return {
        "machine": machine, "status": status,
        "page_before": page_before, "page_after": page_after,
        "renamed": bool(page_before and page_after and page_before != page_after),
        "wiki_regions": wiki_regions, "trivia_sections": trivia_sections,
        "fields": fields, "trivia_text": trivia_text,
    }
