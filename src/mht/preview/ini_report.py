"""Concise, source-backed report for the Gaming History INI stage.

Presentation only: preserve missing/zero distinctions and do not infer errors.
"""
from __future__ import annotations

from typing import Any

DISTRIBUTION_LIMIT = 12

FILES = (
    ("game_status", "Game Or No Game.ini", "Game-status classifications"),
    ("category", "Machine Category.ini", "Machine categories"),
    ("type", "Machine Type.ini", "Machine types"),
)


def _map(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _string(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _rank(mapping: Any) -> dict:
    rows = [{"name": str(name), "count": value} for name, value in _map(mapping).items()
            if _count(value) is not None]
    rows.sort(key=lambda item: (-item["count"], item["name"].casefold()))
    return {"rows": rows[:DISTRIBUTION_LIMIT], "total_groups": len(rows),
            "shown_groups": min(len(rows), DISTRIBUTION_LIMIT)}


def _file_name(record: dict, provenance: dict, key: str, default: str) -> str | None:
    # The builder uses the logical key as a filename fallback; it is not evidence.
    for candidate in (provenance.get("zip_member"), record.get("filename"), provenance.get("name")):
        name = _string(candidate)
        if name and name.casefold() != key.casefold():
            return name
    return None


def build_ini_report(summary: dict) -> dict:
    """Prepare bounded file, coverage and classification summaries for HTML."""
    summary = _map(summary)
    ini = _map(summary.get("ini"))
    files = _map(ini.get("files"))
    totals = _map(summary.get("totals"))
    versions = _map(_map(summary.get("header")).get("versions"))
    inputs = _map(summary.get("provenance")).get("inputs")
    inputs = inputs if isinstance(inputs, list) else []

    coverage = []
    for key, label in (
        ("unique_machine_names_union", "Distinct machine names across all three INIs"),
        ("with_game_status", "With game-status classification"),
        ("missing_in_game_status", "Missing game-status classification"),
        ("with_category", "With machine category"),
        ("missing_in_category", "Missing machine category"),
        ("with_type", "With machine type"),
        ("missing_in_type", "Missing machine type"),
    ):
        number = _count(totals.get(key))
        if number is not None:
            coverage.append({"label": label, "value": number, "path": f"totals.{key}"})

    cards = []
    observations = []
    for index, (key, friendly, title) in enumerate(FILES):
        record = _map(files.get(key))
        provenance = _map(inputs[index]) if index < len(inputs) else {}
        version = _map(record.get("version"))
        metrics = []
        for field, label in (
            ("entries_listed", "Assignments listed"),
            ("entries_indexed", "Distinct machines indexed"),
            ("sections_total", "Classification sections"),
            ("machines_with_multiple_sections", "Machines in multiple sections"),
            ("duplicate_assignments", "Duplicate assignments across sections"),
        ):
            number = _count(record.get(field))
            if number is not None:
                metrics.append({"label": label, "value": number})
        for field, label in (
            ("machines_with_multiple_sections", "Machines in multiple sections"),
            ("duplicate_assignments", "Duplicate assignments across sections"),
        ):
            number = _count(record.get(field))
            if number is not None and number > 0:
                observations.append({"label": f"{friendly}: {label}", "count": number,
                                     "path": f"ini.files.{key}.{field}"})

        cards.append({
            "key": key, "title": title, "friendly_filename": friendly,
            "source_filename": _file_name(record, provenance, key, friendly),
            "archive": _string(provenance.get("zip_archive")),
            "source_modified": _string(provenance.get("zip_member_modified")),
            "encoding": _string(record.get("encoding")) or _string(provenance.get("encoding")),
            "mame_version": _string(version.get("mame_version")) or _string(provenance.get("declared_mame_version")),
            "mame_build": _string(version.get("mame_build")) or _string(provenance.get("declared_mame_build")),
            "metrics": metrics,
            "listed": _rank(record.get("section_counts_listed")),
            "unique": _rank(record.get("section_counts_unique")),
            "listed_path": f"ini.files.{key}.section_counts_listed",
            "unique_path": f"ini.files.{key}.section_counts_unique",
        })

    errors = summary.get("errors")
    error_count = len(errors) if isinstance(errors, list) else None
    if error_count:
        observations.append({"label": "Recorded INI summary errors", "count": error_count,
                             "path": "errors"})

    return {"coverage": coverage, "files": cards, "observations": observations,
            "errors_count": error_count, "versions": versions,
            "source_generated": _string(ini.get("generated_at")),
            "distribution_limit": DISTRIBUTION_LIMIT}
