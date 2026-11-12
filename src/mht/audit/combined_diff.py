"""Combine MHT Wiki and rendered GH Trivia changes without double counting.

Read-only and independent of the CLI/Preview. Newly published and withdrawn
machines are already full-page changes, so Trivia is compared only for machines
published in both releases.
"""
from __future__ import annotations

from typing import Any

from mht.audit.release_diff import _load_release, compare_wiki_releases
from mht.audit.trivia_diff import compare_trivia_sections


def compare_release_content(before_version: str, after_version: str) -> dict[str, Any]:
    """Return a combined, JSON-serialisable report for two completed releases."""
    wiki = compare_wiki_releases(before_version, after_version)

    # Reuse the validated published-game and page-mapping inputs.
    before_doc, old_pages = _load_release(before_version)
    after_doc, new_pages = _load_release(after_version)
    old_ids = set(before_doc["games"])
    new_ids = set(after_doc["games"])

    trivia = compare_trivia_sections(before_version, after_version, old_ids, new_ids)
    wiki_changed = (
        set(wiki["modified"])
        | {record["machine"] for record in wiki["added"]}
        | {record["machine"] for record in wiki["withdrawn"]}
    )
    trivia_changed = set(trivia["changed_machines"])
    overlap = wiki_changed & trivia_changed
    trivia_only = trivia_changed - wiki_changed
    all_affected = wiki_changed | trivia_changed

    # A title change can introduce two distinct title identities for one machine.
    affected_titles = {
        page
        for machine in all_affected
        for page in (old_pages.get(machine), new_pages.get(machine))
        if page is not None
    }

    affected: dict[str, dict[str, Any]] = {}
    for machine in sorted(all_affected):
        wiki_modification = wiki["modified"].get(machine)
        if machine in old_ids and machine not in new_ids:
            status = "withdrawn"
        elif machine in new_ids and machine not in old_ids:
            status = "added"
        else:
            status = "modified"
        affected[machine] = {
            "status": status,
            "page_before": old_pages.get(machine),
            "page_after": new_pages.get(machine),
            "wiki_regions": wiki_modification["affected_regions"] if wiki_modification else [],
            "trivia_sections": trivia["changed_machines"].get(machine, []),
        }

    return {
        "before_version": before_version,
        "after_version": after_version,
        "wiki_schema": wiki["wiki_schema"],
        "scope": (
            "Generated Wiki JSON, page mappings and rendered GH Trivia sections; "
            "excludes diagnostic metadata, raw-source-only changes and live Wiki edits"
        ),
        "counts": {
            **wiki["counts"],
            "wiki_affected_machines": len(wiki_changed),
            "trivia_changed_machines": len(trivia_changed),
            "changed_in_both": len(overlap),
            "trivia_only_machines": len(trivia_only),
            "affected_machines": len(all_affected),
            "distinct_affected_page_titles": len(affected_titles),
            "changed_trivia_sections": trivia["counts"]["changed_sections"],
        },
        "added": wiki["added"],
        "withdrawn": wiki["withdrawn"],
        "renamed": wiki["renamed"],
        "modified": wiki["modified"],
        "changed_field_counts": wiki["changed_field_counts"],
        "affected_region_counts": {
            **wiki["affected_region_counts"],
            **{
                f"GH Trivia: {section}": count
                for section, count in trivia["changed_section_counts"].items()
            },
        },
        "trivia": trivia,
        "affected": affected,
    }
