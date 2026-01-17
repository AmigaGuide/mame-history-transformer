from __future__ import annotations

"""
Home-page overview builders.

These convert full JSON summaries into a small set of headlines and a handful of
high-value findings, suitable for the home page.
"""

from typing import Any, Dict, List

from .formatting import as_dict, as_list, overview_headlines, top_n_from_mapping
from .preview_data import JsonDict


def build_mame_overview(mame_summary: JsonDict) -> JsonDict:
    totals = as_dict(mame_summary.get("totals"))

    headlines = overview_headlines(
        [
            ("Total machines", totals.get("total_machines", "unknown")),
            ("Total parents", totals.get("total_parents", "unknown")),
            ("Total clones", totals.get("total_clones", "unknown")),
            ("is bios", totals.get("total_isbios", totals.get("total_is_bios", "unknown"))),
            ("is device", totals.get("total_isdevice", totals.get("total_is_device", "unknown"))),
            ("is mechanical", totals.get("total_ismechanical", "unknown")),
            ("requires samples", totals.get("total_requires_samples", "unknown")),
        ]
    )

    findings: List[JsonDict] = []

    for title, key in [
        ("Top display types", "display_types_distribution"),
        ("Top controls (players)", "players_per_machine_distribution"),
    ]:
        dist = totals.get(key)
        if isinstance(dist, dict) and dist:
            findings.append({"title": title, "items": top_n_from_mapping(dist, 5)})

    invalid = totals.get("invalid_displays_dropped")
    if isinstance(invalid, dict) and invalid.get("count"):
        examples = as_list(invalid.get("examples"))
        lines = [f"Count: {invalid.get('count')}"]
        for ex in examples[:5]:
            if isinstance(ex, dict):
                lines.append(
                    f"{ex.get('machine', '?')}: {ex.get('type', '?')} "
                    f"{ex.get('width', '?')}x{ex.get('height', '?')} "
                    f"{ex.get('tag', '')}".strip()
                )
            else:
                lines.append(str(ex))
        findings.append({"title": "Invalid displays dropped (examples)", "items": lines})

    anomalies = as_dict(mame_summary.get("anomalies"))
    if anomalies.get("count"):
        examples2 = as_list(anomalies.get("examples"))
        lines2 = [f"Count: {anomalies.get('count')}"] + [str(ex) for ex in examples2[:5]]
        findings.append({"title": "Anomalies (examples)", "items": lines2})

    return {"headlines": headlines, "findings": findings}


def build_history_overview(history_summary: JsonDict) -> JsonDict:
    totals = as_dict(history_summary.get("totals"))
    sections_found = as_dict(history_summary.get("sections_found"))
    found = as_dict(history_summary.get("found"))

    overview_sf = as_dict(as_dict(sections_found.get("overview")))
    technical_sf = as_dict(as_dict(sections_found.get("technical")))

    headlines = overview_headlines(
        [
            ("Systems total", totals.get("systems_total", totals.get("total_systems", "unknown"))),
            ("Software total", totals.get("software_total", totals.get("total_software", "unknown"))),
            ("Entries total", totals.get("entries_total", totals.get("total_entries", "unknown"))),
            ("Systems with PORTS", totals.get("systems_with_ports", "unknown")),
            ("Overview sections (systems)", overview_sf.get("systems_count", "unknown")),
            ("Technical sections (systems)", technical_sf.get("systems_count", "unknown")),
        ]
    )

    findings: List[JsonDict] = []

    blocks = as_dict(found.get("blocks"))
    by_type = blocks.get("by_type")
    if isinstance(by_type, dict) and by_type:
        findings.append({"title": "Trivia blocks by type (top 5)", "items": top_n_from_mapping(by_type, 5)})

    platforms_found = as_dict(found.get("platforms_found"))
    by_platform = platforms_found.get("by_platform")
    if isinstance(by_platform, dict) and by_platform:
        findings.append({"title": "Platforms found (top 5)", "items": top_n_from_mapping(by_platform, 5)})

    anomalies = as_dict(history_summary.get("anomalies"))
    if anomalies:
        lines: List[str] = []
        for k, v in anomalies.items():
            if isinstance(v, dict) and v.get("count"):
                lines.append(f"{k}: {v.get('count')}")
            elif isinstance(v, int) and v > 0:
                lines.append(f"{k}: {v}")
        if lines:
            findings.append({"title": "Anomaly groups (non-zero)", "items": lines[:5]})

    return {"headlines": headlines, "findings": findings}


def build_ini_overview(ini_summary: JsonDict) -> JsonDict:
    ini = as_dict(ini_summary.get("ini"))
    files = as_dict(ini.get("files"))

    def _sec_counts(file_key: str) -> Dict[str, int]:
        f = as_dict(files.get(file_key))
        sc = f.get("section_counts_listed")
        return sc if isinstance(sc, dict) else {}

    game_counts = _sec_counts("game_status")
    cat_counts = _sec_counts("category")
    type_counts = _sec_counts("type")

    type_na = type_counts.get("<not available>", 0)
    type_total = sum(int(v) for v in type_counts.values() if isinstance(v, int))
    distinct_types = len([k for k in type_counts.keys() if k != "<not available>"])

    return {
        "game_or_no_game": [
            {"label": "<not available>", "value": game_counts.get("<not available>", "unknown")},
            {"label": "Game", "value": game_counts.get("Game", "unknown")},
            {"label": "No Game", "value": game_counts.get("No Game", "unknown")},
        ],
        "machine_category": [
            {"label": "Arcade", "value": cat_counts.get("Arcade", "unknown")},
            {"label": "Coin-Op (Games)", "value": cat_counts.get("Coin-Op (Games)", "unknown")},
            {"label": "Coin-Op (Non-Games)", "value": cat_counts.get("Coin-Op (Non-Games)", "unknown")},
            {"label": "Computers", "value": cat_counts.get("Computers", "unknown")},
            {"label": "Consoles", "value": cat_counts.get("Consoles", "unknown")},
            {"label": "Electronic", "value": cat_counts.get("Electronic", "unknown")},
            {"label": "Gambling", "value": cat_counts.get("Gambling", "unknown")},
            {"label": "Hardware", "value": cat_counts.get("Hardware", "unknown")},
        ],
        "machine_type": [
            {"label": "<not available>", "value": type_na},
            {"label": "Types observed", "value": distinct_types},
            {"label": "Total entries", "value": type_total},
        ],
    }


def build_transform_overview(transform_summary: JsonDict) -> JsonDict:
    counts = as_dict(transform_summary.get("counts"))
    selection = as_dict(transform_summary.get("selection"))
    ports = as_dict(transform_summary.get("ports"))

    headlines = overview_headlines(
        [
            ("MAME total", counts.get("mame_total", "unknown")),
            ("Parents total", counts.get("parents_total", "unknown")),
            ("Clones total", counts.get("clones_total", "unknown")),
            ("Eligible parents", counts.get("eligible_parents", "unknown")),
            ("Final included", counts.get("final_included", selection.get("included_parents_total", "unknown"))),
            ("Parents with clones", counts.get("parents_with_clones", "unknown")),
        ]
    )

    findings: List[JsonDict] = []

    excluded = transform_summary.get("excluded_parents_by_reason")
    if isinstance(excluded, dict) and excluded:
        findings.append({"title": "Excluded by reason (top 5)", "items": top_n_from_mapping(excluded, 5)})

    if ports:
        lines: List[str] = []

        gh_arcade = ports.get("gh_arcade_entries_with_ports_total")
        if gh_arcade is not None:
            lines.append(f"GH arcade entries with ports: {gh_arcade}")

        own = ports.get("included_parents_with_own_ports")
        if isinstance(own, dict):
            lines.append(f"Included parents with own ports: {own.get('count', 'unknown')}")

        clones = ports.get("included_clones_with_ports")
        if isinstance(clones, dict):
            lines.append(f"Included clones with ports: {clones.get('count', 'unknown')}")

        out_scope = ports.get("gh_arcade_entries_with_ports_excluded_by_ini")
        if isinstance(out_scope, dict):
            lines.append(f"Ports excluded by INI scope: {out_scope.get('count', 'unknown')}")

        if lines:
            findings.append({"title": "PORTS coverage", "items": lines[:5]})

    return {"headlines": headlines, "findings": findings}
