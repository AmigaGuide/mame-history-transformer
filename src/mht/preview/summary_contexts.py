from __future__ import annotations

"""
Summary page context builders.

These prepare template-friendly dicts for the /summary/* pages. We keep templates
simple by providing explicit lists/pairs, rather than relying on dict iteration
and type checks inside Jinja.
"""

from typing import Any, Dict, List, Tuple

from .formatting import as_dict, as_list, pretty_json, sorted_pairs_from_mapping
from .preview_data import JsonDict


def prep_mame_summary_page_context(mame_summary: JsonDict) -> JsonDict:
    header = as_dict(mame_summary.get("header"))
    totals = as_dict(mame_summary.get("totals"))

    dist_specs: List[Tuple[str, str]] = [
        ("Players per machine", "players_per_machine_distribution"),
        ("Buttons per machine", "buttons_per_machine_distribution"),
        ("Display types", "display_types_distribution"),
        ("Orientations", "orientations_distribution"),
        ("Refresh rates (rounded)", "refresh_rates_rounded_distribution"),
        ("Speakers per machine", "speakers_per_machine_distribution"),
        ("Sound channels per machine", "sound_channels_per_machine_distribution"),
        ("CPU manufacturers", "cpu_manufacturers_distribution"),
        ("CPU families", "cpu_families_distribution"),
    ]

    distributions: List[Tuple[str, List[Tuple[str, Any]]]] = []
    for title, key in dist_specs:
        dist = totals.get(key)
        if isinstance(dist, dict) and dist:
            distributions.append((title, sorted_pairs_from_mapping(dist)))

    example_groups: List[JsonDict] = []

    invalid_displays = totals.get("invalid_displays_dropped")
    if isinstance(invalid_displays, dict) and (invalid_displays.get("count") or invalid_displays.get("examples")):
        lines: List[str] = []
        cnt = invalid_displays.get("count")
        if cnt is not None:
            lines.append(f"Count: {cnt}")

        examples = as_list(invalid_displays.get("examples"))
        for ex in examples[:25]:
            if isinstance(ex, dict):
                machine = ex.get("machine", "?")
                dtype = ex.get("type", "?")
                w = ex.get("width", "?")
                h = ex.get("height", "?")
                tag = ex.get("tag", "")
                line = f"{machine}: {dtype} {w}x{h}"
                if tag:
                    line = f"{line} ({tag})"
                lines.append(line)
            else:
                lines.append(str(ex))

        example_groups.append({"title": "Invalid displays dropped", "items": lines})

    anomalies = mame_summary.get("anomalies")
    if isinstance(anomalies, dict) and (anomalies.get("count") or anomalies.get("examples")):
        lines2: List[str] = []
        cnt2 = anomalies.get("count")
        if cnt2 is not None:
            lines2.append(f"Count: {cnt2}")
        examples2 = as_list(anomalies.get("examples"))
        for ex in examples2[:25]:
            lines2.append(str(ex))
        example_groups.append({"title": "Anomalies", "items": lines2})

    return {
        "header": header,
        "totals": totals,
        "distributions": distributions,
        "example_groups": example_groups,
        "raw_json": pretty_json(mame_summary),
    }


def prep_history_summary_page_context(history_summary: JsonDict) -> JsonDict:
    header = as_dict(history_summary.get("header"))
    totals = as_dict(history_summary.get("totals"))
    sections_found = as_dict(history_summary.get("sections_found"))
    found = as_dict(history_summary.get("found"))

    found_blocks_by_type: List[Tuple[str, Any]] = []
    blocks = as_dict(found.get("blocks"))
    by_type = blocks.get("by_type")
    if isinstance(by_type, dict) and by_type:
        found_blocks_by_type = sorted_pairs_from_mapping(by_type)

    found_platforms: List[Tuple[str, Any]] = []
    platforms_found = as_dict(found.get("platforms_found"))
    by_platform = platforms_found.get("by_platform")
    if isinstance(by_platform, dict) and by_platform:
        found_platforms = sorted_pairs_from_mapping(by_platform)

    anomalies_nonzero: List[str] = []
    anomalies = history_summary.get("anomalies")
    if isinstance(anomalies, dict):
        for group_name, obj in anomalies.items():
            if isinstance(obj, dict):
                c = obj.get("count")
                if isinstance(c, int) and c > 0:
                    anomalies_nonzero.append(f"{group_name}: {c}")
            elif isinstance(obj, int) and obj > 0:
                anomalies_nonzero.append(f"{group_name}: {obj}")
        anomalies_nonzero.sort()

    return {
        "header": header,
        "totals": totals,
        "sections_found": sections_found,
        "found_blocks_by_type": found_blocks_by_type,
        "found_platforms": found_platforms,
        "anomalies_nonzero": anomalies_nonzero,
        "raw_json": pretty_json(history_summary),
    }


def prep_ini_summary_page_context(ini_summary: JsonDict) -> JsonDict:
    """
    Template-friendly context for summary_ini.html.

    We avoid relying on dict ".items" directly in templates by providing
    explicit lists of pairs.
    """
    header = as_dict(ini_summary.get("header"))
    ini = as_dict(ini_summary.get("ini"))
    files = as_dict(ini.get("files"))

    file_cards: List[JsonDict] = []
    for key in ["game_status", "category", "type"]:
        f = as_dict(files.get(key))
        section_counts = f.get("section_counts_listed")
        pairs = sorted_pairs_from_mapping(section_counts) if isinstance(section_counts, dict) else []
        file_cards.append(
            {
                "key": key,
                "filename": f.get("filename"),
                "version": f.get("version"),
                "entries_listed": f.get("entries_listed"),
                "sections_total": f.get("sections_total"),
                "section_counts_pairs": pairs,
                "raw": f,
            }
        )

    totals = as_dict(ini_summary.get("totals"))

    return {
        "header": header,
        "totals": totals,
        "file_cards": file_cards,
        "raw_json": pretty_json(ini_summary),
    }


def prep_transform_summary_page_context(transform_summary: JsonDict) -> JsonDict:
    """
    Template-friendly context for summary_transform.html.

    Provides both raw dicts and pre-sorted lists so templates can iterate safely.
    """
    header = as_dict(transform_summary.get("header"))
    counts = as_dict(transform_summary.get("counts"))
    selection = as_dict(transform_summary.get("selection"))
    ports = as_dict(transform_summary.get("ports"))

    excluded = transform_summary.get("excluded_parents_by_reason")
    excluded_pairs = sorted_pairs_from_mapping(excluded) if isinstance(excluded, dict) else []

    return {
        "header": header,
        "counts": counts,
        "selection": selection,
        "ports": ports,
        "excluded_pairs": excluded_pairs,
        "raw_json": pretty_json(transform_summary),
    }
