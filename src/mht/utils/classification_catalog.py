"""
Combine source-specific MAME machine classifications.

This module preserves Gaming History and progetto-SNAPS
classifications independently. It does not decide which
machines qualify for ExoticA output.
"""

from __future__ import annotations

from typing import Any


def build_classification_catalog(
    mame: dict[str, dict[str, Any]],
    gh_classifications: dict[str, dict[str, Any]],
    snaps_classifications: dict[str, dict[str, str]],
    gh_historical_snapshot: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Combine current and historical classifications.

    Source-specific evidence is preserved independently.
    Missing classifications remain absent.

    This function does not perform eligibility selection.
    """
    catalog = {}
    historical = (
        gh_historical_snapshot
        if gh_historical_snapshot is not None
        else {}
    )

    for machine, info in mame.items():
        if not isinstance(info, dict):
            raise ValueError(
                f"Invalid MAME record for {machine}"
            )

        gh = gh_classifications.get(machine)
        snaps = snaps_classifications.get(machine)
        history = historical.get(machine)

        for label, record in (
            ("Gaming History", gh),
            ("SNAPS", snaps),
            ("Historical Gaming History", history),
        ):
            if record is not None and not isinstance(record, dict):
                raise ValueError(
                    f"Invalid {label} record for {machine}"
                )

        catalog[machine] = {
            "mame": {
                "cloneof": info.get("cloneof"),
                "isbios": info.get("isbios"),
                "isdevice": info.get("isdevice"),
                "ismechanical": info.get("ismechanical"),
            },
            "gaming_history": (
                {
                    "game_status": gh.get("game_status"),
                    "category": list(gh.get("category") or []),
                    "type": gh.get("type"),
                }
                if gh is not None else None
            ),
            "gaming_history_historical": (
                {
                    "category": list(history.get("category") or []),
                    "source_release": history.get("source_release"),
                    "requested_release": history.get("requested_release"),
                    "status": history.get("status"),
                }
                if history is not None else None
            ),
            "snaps": (
                {
                    "group": snaps.get("group"),
                    "category": snaps.get("category"),
                    "subcategory": snaps.get("subcategory"),
                }
                if snaps is not None else None
            ),
        }

    return catalog
