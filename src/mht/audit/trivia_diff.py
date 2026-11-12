"""Read-only comparison of the rendered GH Trivia sections in two MHT releases.

Compares sections for machines published in both releases. Diagnostics and
source text are not page content and do not trigger changes. Results can be
merged with the published Wiki comparison by stable MAME machine identifier.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mht.utils.paths import gh_system_trivia_path


# Keys used by the current Preview template when rendering each block type.
_RENDERED_KEYS = {
    "paragraph": ("type", "text"),
    "subheading": ("type", "text"),
    "bullet_list": ("type", "items"),
    "numbered_list": ("type", "items"),
    "pair": ("type", "label", "value"),
}


def _read_trivia(version: str) -> dict[str, Any]:
    path = gh_system_trivia_path(version)
    try:
        with path.open(encoding="utf-8") as stream:
            result = json.load(stream)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read GH Trivia for {version} ({path}): {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError(f"Invalid GH Trivia dataset for {version}: expected an object")
    # The producer writes a direct machine->record mapping; reject unexpected roots
    # rather than accidentally treating a wrapper as a machine name.
    if "systems" in result or "games" in result:
        raise ValueError(f"Unexpected GH Trivia root layout for {version}: {path}")
    return result


def _rendered_blocks(record: dict[str, Any] | None) -> dict[str, list[tuple[Any, ...]]]:
    """Project only content used by the current Preview's Trivia renderer."""
    if record is None:
        return {}
    sections = record.get("sections", {})
    if not isinstance(sections, dict):
        raise ValueError("Trivia 'sections' must be an object")
    result: dict[str, list[tuple[Any, ...]]] = {}
    for section_name, section in sections.items():
        if not isinstance(section, dict) or not isinstance(section.get("blocks"), list):
            raise ValueError(f"Invalid Trivia section {section_name!r}")
        content: list[tuple[Any, ...]] = []
        for block in section["blocks"]:
            if not isinstance(block, dict):
                raise ValueError(f"Invalid block in Trivia section {section_name!r}")
            kind = block.get("type")
            if kind not in _RENDERED_KEYS:
                raise ValueError(f"Unsupported Trivia block type {kind!r} in {section_name!r}")
            keys = _RENDERED_KEYS[kind]
            # Lists are ordered, but a JSON list isn't hashable; make immutable.
            values = tuple(tuple(block.get(k, [])) if k == "items" else block.get(k) for k in keys)
            content.append(values)
        # An absent section and an empty section both render no content.
        if content:
            result[section_name] = content
    return result


def compare_trivia_sections(
    before_version: str,
    after_version: str,
    published_before: set[str],
    published_after: set[str],
) -> dict[str, Any]:
    """Compare rendered GH Trivia sections for continuing, published machines.

    A release's entire GH Trivia dataset is loaded, but unpublished machines
    are excluded from the Wiki-update comparison. New/withdrawn Wiki pages
    are already classified by the Wiki comparator.
    """
    old = _read_trivia(before_version)
    new = _read_trivia(after_version)
    common = sorted(published_before & published_after)
    changed: dict[str, list[str]] = {}
    section_counts: dict[str, int] = {}
    no_trivia_both = 0
    for machine in common:
        prior = old.get(machine)
        current = new.get(machine)
        if prior is not None and not isinstance(prior, dict):
            raise ValueError(f"Invalid Trivia record for {machine!r} in {before_version}")
        if current is not None and not isinstance(current, dict):
            raise ValueError(f"Invalid Trivia record for {machine!r} in {after_version}")
        if prior is None and current is None:
            no_trivia_both += 1
        old_sections = _rendered_blocks(prior)
        new_sections = _rendered_blocks(current)
        sections = sorted(
            name for name in old_sections.keys() | new_sections.keys()
            if old_sections.get(name) != new_sections.get(name)
        )
        if sections:
            changed[machine] = sections
            for name in sections:
                section_counts[name] = section_counts.get(name, 0) + 1

    return {
        "before_version": before_version,
        "after_version": after_version,
        "scope": "Rendered GH Trivia sections on continuing published machines; no parser metadata or raw-source-only changes",
        "counts": {
            "continuing_published_machines": len(common),
            "machines_with_changed_trivia": len(changed),
            "changed_sections": sum(map(len, changed.values())),
            "no_trivia_record_in_either_release": no_trivia_both,
        },
        "changed_section_counts": dict(sorted(section_counts.items())),
        "changed_machines": changed,
    }
