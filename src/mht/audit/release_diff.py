"""Read-only comparison of two MHT published Wiki datasets.

This compares generated Wiki record content, not live ExoticA pages or
Gaming History Trivia sections.  MAME machine IDs are stable comparison keys.
The result is JSON-serialisable for future CLI and Preview consumers.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mht.utils.paths import exotica_pages_path, exotica_wiki_path


FIELD_REGIONS: dict[str, str] = {
    "opening_sentence": "Opening sentence",
    "mame_titles_display": "MAME titles",
    "ports_display": "PORTS",
    "roms_display": "MAME information panel",
    "chips_display": "MAME information panel",
    "displays_display": "MAME information panel",
    "controls_display": "MAME information panel",
    "manufacturer": "MAME information panel",
    "year": "MAME information panel",
    "gh_ids": "GH references",
    "wiki_page_name": "Page name",
    "wiki_redirects": "Redirects",
}


def _read_object(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _load_release(version: str) -> tuple[dict[str, Any], dict[str, str]]:
    wiki = _read_object(exotica_wiki_path(version))
    pages_doc = _read_object(exotica_pages_path(version))
    games = wiki.get("games")
    pages = pages_doc.get("pages")
    if not isinstance(games, dict) or not isinstance(pages, dict):
        raise ValueError(f"Invalid Wiki or pages dataset for release {version}")
    if any(not isinstance(k, str) or not isinstance(v, dict) for k, v in games.items()):
        raise ValueError(f"Invalid Wiki game records for release {version}")
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in pages.items()):
        raise ValueError(f"Invalid page mapping for release {version}")
    if set(games) != set(pages):
        raise ValueError(f"Wiki game IDs and page mapping disagree for release {version}")
    return wiki, pages


def compare_wiki_releases(before_version: str, after_version: str) -> dict[str, Any]:
    """Compare two completed, same-schema published Wiki outputs.

    No parsing, stage execution, output writing, or active-release changes.
    Refuse differing schemas instead of miscounting format changes as edits.
    """
    if before_version == after_version:
        raise ValueError("Choose two different MAME release versions")

    before, old_pages = _load_release(before_version)
    after, new_pages = _load_release(after_version)
    old_header, new_header = before.get("header", {}), after.get("header", {})
    old_schema = old_header.get("schema_version") if isinstance(old_header, dict) else None
    new_schema = new_header.get("schema_version") if isinstance(new_header, dict) else None
    if not old_schema or not new_schema or old_schema != new_schema:
        raise ValueError(
            f"Wiki schemas differ ({old_schema!r} vs {new_schema!r}); "
            "regenerate both releases with compatible MHT code before comparing"
        )

    old_games, new_games = before["games"], after["games"]
    old_ids, new_ids = set(old_games), set(new_games)
    added = sorted(new_ids - old_ids)
    withdrawn = sorted(old_ids - new_ids)
    modified: dict[str, dict[str, Any]] = {}
    field_counts: dict[str, int] = {}
    region_counts: dict[str, int] = {}

    for machine in sorted(old_ids & new_ids):
        old, new = old_games[machine], new_games[machine]
        changed = sorted(
            field for field in (old.keys() | new.keys())
            if old.get(field) != new.get(field)
        )
        old_page, new_page = old_pages[machine], new_pages[machine]
        if not changed and old_page == new_page:
            continue
        regions = sorted({FIELD_REGIONS.get(field, f"Other: {field}") for field in changed})
        if old_page != new_page and "Page name" not in regions:
            regions.append("Page name")
            regions.sort()
        modified[machine] = {
            "page_before": old_page,
            "page_after": new_page,
            "changed_fields": changed,
            "affected_regions": regions,
            "page_name_changed": old_page != new_page,
        }
        for field in changed:
            field_counts[field] = field_counts.get(field, 0) + 1
        for region in regions:
            region_counts[region] = region_counts.get(region, 0) + 1

    affected_machine_ids = set(added) | set(withdrawn) | set(modified)
    affected_page_titles = set()
    for machine in affected_machine_ids:
        if machine in old_pages:
            affected_page_titles.add(old_pages[machine])
        if machine in new_pages:
            affected_page_titles.add(new_pages[machine])

    renamed = sorted(machine for machine, rec in modified.items() if rec["page_name_changed"])
    return {
        "before_version": before_version,
        "after_version": after_version,
        "wiki_schema": old_schema,
        "scope": "Published Wiki JSON and generated page mappings only; excludes GH Trivia sections",
        "counts": {
            "before_games": len(old_ids),
            "after_games": len(new_ids),
            "added": len(added),
            "withdrawn": len(withdrawn),
            "modified": len(modified),
            "unchanged": len((old_ids & new_ids) - set(modified)),
            "affected_machines": len(affected_machine_ids),
            "distinct_affected_page_titles": len(affected_page_titles),
            "page_name_changes": len(renamed),
        },
        "added": [{"machine": machine, "page": new_pages[machine]} for machine in added],
        "withdrawn": [{"machine": machine, "page": old_pages[machine]} for machine in withdrawn],
        "renamed": [{"machine": machine, "before": old_pages[machine], "after": new_pages[machine]} for machine in renamed],
        "modified": modified,
        "changed_field_counts": dict(sorted(field_counts.items())),
        "affected_region_counts": dict(sorted(region_counts.items())),
    }
