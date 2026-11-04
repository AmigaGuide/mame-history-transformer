"""
Load and validate reviewed PS-SNAPS genre descriptions for ExoticA LiT.

Classification identifiers are preserved exactly as supplied by PS-SNAPS.
Descriptions are complete introductory phrases, including their article.

Unknown classifications are errors, not opportunities to guess wording.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Mapping


GenreKey = tuple[str, str, str]
GenreLookup = dict[GenreKey, str]

GENRE_DESCRIPTIONS_PATH = (
    Path(__file__).resolve().with_name("snaps_genre_descriptions.json")
)

_REQUIRED_FIELDS = {
    "group",
    "category",
    "subcategory",
    "phrase",
}


def load_approved_genres(
    path: Path = GENRE_DESCRIPTIONS_PATH,
) -> GenreLookup:
    """Load the approved vocabulary, rejecting malformed or duplicate entries."""
    try:
        entries = json.loads(
            Path(path).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Cannot load approved SNAPS vocabulary: {exc}"
        ) from exc

    if not isinstance(entries, list) or not entries:
        raise ValueError(
            "Approved SNAPS vocabulary must be a non-empty JSON array."
        )

    lookup: GenreLookup = {}

    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(
                f"SNAPS vocabulary entry {index} must be an object."
            )

        if set(entry) != _REQUIRED_FIELDS:
            raise ValueError(
                f"SNAPS vocabulary entry {index} must contain exactly "
                "group, category, subcategory and phrase."
            )

        for field in _REQUIRED_FIELDS:
            value = entry[field]
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
            ):
                raise ValueError(
                    f"Invalid {field!r} in SNAPS vocabulary entry {index}."
                )

        key: GenreKey = (
            entry["group"],
            entry["category"],
            entry["subcategory"],
        )

        if key in lookup:
            raise ValueError(
                f"Duplicate approved SNAPS classification: {key!r}"
            )

        phrase = entry["phrase"]

        if not re.match(r"^an? \S", phrase):
            raise ValueError(
                f"SNAPS description must begin with 'a' or 'an': "
                f"{key!r} -> {phrase!r}"
            )

        lookup[key] = phrase

    return lookup


def validate_published_genres(
    published_machines: Iterable[str],
    snaps_map: Mapping[str, dict],
    lookup: Mapping[GenreKey, str],
) -> None:
    """Require an approved phrase for every published LiT machine."""
    missing: dict[GenreKey, list[str]] = {}
    missing_records: list[str] = []

    for machine in sorted(set(published_machines)):
        classification = snaps_map.get(machine)

        if not isinstance(classification, dict):
            missing_records.append(machine)
            continue

        values = (
            classification.get("group"),
            classification.get("category"),
            classification.get("subcategory"),
        )

        if any(
            not isinstance(value, str) or not value.strip()
            for value in values
        ):
            missing_records.append(machine)
            continue

        key: GenreKey = values

        if key not in lookup:
            missing.setdefault(key, []).append(machine)

    if not missing and not missing_records:
        return

    lines = [
        "Unapproved or missing PS-SNAPS classifications "
        "prevent LiT publication."
    ]

    if missing_records:
        lines.append(
            "Missing or incomplete SNAPS records: "
            + ", ".join(sorted(missing_records))
        )

    for key, machines in sorted(missing.items()):
        lines.append(
            f"{key!r}: {', '.join(sorted(machines))}"
        )

    raise ValueError("\n".join(lines))
