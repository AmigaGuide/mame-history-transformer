"""
Historical Gaming History Machine Category lookups.

Reads observations from the historical category catalogue.

This module does not infer new classifications, alter
machine eligibility or change ExoticA outputs.
"""

from __future__ import annotations

from bisect import bisect_right
from typing import Any


def normalise_release(value: str | int) -> str:
    """
    Return a four-digit MAME release identifier.

    Accepts 287, '0287' and '0.287'.
    """
    if isinstance(value, bool):
        raise ValueError("Invalid MAME release")

    text = str(value).strip()

    if text.startswith("0."):
        text = text[2:]

    if not text.isdecimal() or len(text) > 4:
        raise ValueError(
            f"Invalid MAME release: {value!r}"
        )

    return text.zfill(4)


def lookup_gh_category(
    catalog: dict[str, Any],
    machine: str,
    release: str | int,
) -> dict[str, Any] | None:
    """
    Find the most recent category observation at or
    before the requested MAME release.

    Returns None if no earlier observation exists.

    The result includes:
      category: list of original GH category labels
      source_release: release containing the observation
      requested_release: queried MAME release
      status: 'observed' or 'carried_forward'

    No future observation may influence the result.
    """
    requested = normalise_release(release)

    machines = catalog.get("machines", {})
    record = machines.get(machine)

    if not isinstance(record, dict):
        return None

    observations = record.get("observations", {})

    if not isinstance(observations, dict):
        raise ValueError(
            f"Invalid observations for {machine}"
        )

    # Normalise observed release keys before sorting,
    # retaining their associated category assignments.
    by_release = {}

    for version, categories in observations.items():
        key = normalise_release(version)

        if key in by_release:
            raise ValueError(
                f"Duplicate release observation: "
                f"{machine} / {key}"
            )

        if not isinstance(categories, list):
            raise ValueError(
                f"Invalid categories: {machine} / {key}"
            )

        by_release[key] = categories

    releases = sorted(by_release)
    position = bisect_right(releases, requested) - 1

    if position < 0:
        return None

    source_release = releases[position]

    return {
        "category": list(by_release[source_release]),
        "source_release": source_release,
        "requested_release": requested,
        "status": (
            "observed"
            if source_release == requested
            else "carried_forward"
        ),
    }


def build_gh_category_snapshot(
    catalog: dict[str, Any],
    release: str | int,
) -> dict[str, dict[str, Any]]:
    """
    Build the historical GH category lookup for one release.

    Each machine is examined once. A machine is included only
    when an observation exists at or before the requested
    release.

    Source releases are preserved and no future observation
    is used.
    """
    requested = normalise_release(release)
    machines = catalog.get("machines", {})

    if not isinstance(machines, dict):
        raise ValueError("Invalid historical machine catalogue")

    snapshot = {}

    for machine, record in machines.items():
        if not isinstance(record, dict):
            raise ValueError(
                f"Invalid historical machine: {machine}"
            )

        observations = record.get("observations", {})

        if not isinstance(observations, dict):
            raise ValueError(
                f"Invalid observations for {machine}"
            )

        eligible = [
            (normalise_release(version), categories)
            for version, categories in observations.items()
            if normalise_release(version) <= requested
        ]

        if not eligible:
            continue

        source_release, categories = max(
            eligible,
            key=lambda item: item[0],
        )

        if not isinstance(categories, list):
            raise ValueError(
                f"Invalid categories for "
                f"{machine} in {source_release}"
            )

        snapshot[machine] = {
            "category": list(categories),
            "source_release": source_release,
            "requested_release": requested,
            "status": (
                "observed"
                if source_release == requested
                else "carried_forward"
            ),
        }

    return snapshot
