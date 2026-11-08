from __future__ import annotations

"""
Summary page context builders.

These prepare template-friendly dicts for the /summary/* pages. We keep templates
simple by providing explicit lists/pairs, rather than relying on dict iteration
and type checks inside Jinja.
"""

from typing import Any, Dict, List, Tuple

from .formatting import as_dict, as_list, sorted_pairs_from_mapping
from .preview_data import JsonDict
from .history_report import build_history_report
from .mame_report import build_mame_report


def prep_mame_summary_page_context(mame_summary: JsonDict) -> JsonDict:
    """Build a compact, source-backed MAME summary report."""
    return {
        "header": as_dict(mame_summary.get("header")),
        "report": build_mame_report(mame_summary),
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
        "report": build_history_report(history_summary),
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

    # --- NEW: provenance blocks ---
    provenance = as_dict(transform_summary.get("provenance"))
    prov_inputs = provenance.get("inputs")
    prov_outputs = provenance.get("outputs")
    upstream = provenance.get("upstream_summaries")

    prov_inputs_list = [as_dict(x) for x in prov_inputs] if isinstance(prov_inputs, list) else []
    prov_outputs_list = [as_dict(x) for x in prov_outputs] if isinstance(prov_outputs, list) else []
    upstream_dict = as_dict(upstream) if isinstance(upstream, dict) else {}

    return {
        "header": header,
        "counts": counts,
        "selection": selection,
        "ports": ports,
        "excluded_pairs": excluded_pairs,

        # NEW
        "provenance": provenance,
        "prov_inputs": prov_inputs_list,
        "prov_outputs": prov_outputs_list,
        "upstream": upstream_dict,

    }
