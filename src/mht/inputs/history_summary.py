from __future__ import annotations

from typing import Dict

from mht.utils.headers import build_summary_header
from mht.utils.versions import SCHEMA_IDS, schema_version, tool_version

__all__ = ["build_history_summary"]

def build_history_summary(
    *,
    history_version: str | None,
    history_date: str | None,
    parsing_state: Dict,
    systems_count: int,
    software_count: int,
    systems_with_ports: int,
    systems_with_aliases: int,
    total_port_lines_all: int,
) -> Dict:
    """Rebuild the exact summary JSON structure previously in history_parser.py."""

    # platforms_found → collapse to unique systems per platform
    platforms_found_summary = {}
    for platform, data in parsing_state["platforms_found"].items():
        systems_unique = sorted(set(data["systems"]))
        platforms_found_summary[platform] = {
            "systems_count": len(systems_unique),
            "systems": systems_unique,
        }

    # section headings
    _section_heads = dict(parsing_state["section_headings_found"])
    section_headings_block = {
        "unique": len(_section_heads),
        "distribution": dict(sorted(_section_heads.items(), key=lambda kv: kv[0].upper())),
    }

    # platform categories (top-level PORTS headings)
    _cats = dict(parsing_state["platform_categories_found"])
    platform_categories_block = {
        "unique": len(_cats),
        "distribution": dict(sorted(_cats.items(), key=lambda kv: kv[0].upper())),
    }

    summary_platforms_block = {
        "unique": len(platforms_found_summary),
        "by_platform": dict(sorted(platforms_found_summary.items(), key=lambda kv: kv[0].lower())),
    }

    # publishers
    _publishers_map = parsing_state["publishers_found"]
    _by_publisher = {}
    for name, data in _publishers_map.items():
        systems_unique = sorted(set(data["systems"]))
        _by_publisher[name] = {"systems_count": len(systems_unique), "systems": systems_unique}
    publishers_block = {
        "unique": len(_by_publisher),
        "indicators_found": {
            k: parsing_state["publisher_indicators_found"].get(k, 0)
            for k in ("by", "released_by", "other_after_date", "none")
        },
        "by_publisher": dict(sorted(_by_publisher.items(), key=lambda kv: kv[0].lower())),
    }

    titles_items = sorted(parsing_state["titles_found"])
    titles_block = {"unique": len(titles_items), "items": titles_items}

    _region = parsing_state["region_codes"]
    region_codes_block = {
        "unique": len(_region),
        "distribution": dict(sorted(_region.items(), key=lambda kv: (-kv[1], kv[0]))),
    }

    models_items = sorted(parsing_state["models_found"].keys())
    models_block = {"unique": len(models_items), "items": models_items}

    _comments_map = parsing_state["comments_found"]
    comments_block = {
        "unique": len(_comments_map),
        "by_comment": {
            c: sorted(set(sys))
            for c, sys in sorted(_comments_map.items(), key=lambda kv: kv[0].lower())
        },
    }

    _tags_map = parsing_state["additional_tags_found"]
    additional_tags_block = {
        "unique": len(_tags_map),
        "by_tag": {
            tag: {"systems_count": len(set(s)), "systems": sorted(set(s))}
            for tag, s in sorted(_tags_map.items(), key=lambda kv: kv[0].lower())
        },
    }

    overviews_map = parsing_state["systems_with_port_overview"]
    port_overview_block = {
        "count": len(overviews_map),
        "by_system": dict(sorted(overviews_map.items(), key=lambda kv: kv[0].lower())),
    }

    _upc_map = parsing_state["unexpected_platform_categories"]
    _by_category = {}
    systems_affected_set = set()
    for cat, systems in _upc_map.items():
        uniq = sorted(set(systems))
        systems_affected_set.update(uniq)
        _by_category[cat] = {"systems_count": len(uniq), "systems": uniq}
    unexpected_platform_categories_block = {
        "unique": len(_by_category),
        "systems_affected": len(systems_affected_set),
        "by_category": dict(sorted(_by_category.items(), key=lambda kv: kv[0].lower())),
    }

    _oddq_map = parsing_state["odd_quotes"]
    odd_number_of_quotes_block = {
        "count": sum(len(v) for v in _oddq_map.values()),
        "systems_affected": len(_oddq_map),
        "by_system": {sys: lines for sys, lines in sorted(_oddq_map.items(), key=lambda kv: kv[0].lower())},
    }

    _oddb_map = parsing_state["odd_brackets"]
    odd_number_of_brackets_block = {
        "count": sum(len(v) for v in _oddb_map.values()),
        "systems_affected": len(_oddb_map),
        "by_system": {sys: lines for sys, lines in sorted(_oddb_map.items(), key=lambda kv: kv[0].lower())},
    }

    _pms_list = parsing_state.get("anomalies", {}).get("ports_missing_subheadings", [])
    _pms_map = {}
    for rec in _pms_list:
        sys = rec.get("system")
        exc = rec.get("excerpt", "")
        if sys:
            _pms_map[sys] = exc
    ports_missing_subheadings_block = {
        "count": len(_pms_map),
        "by_system": dict(sorted(_pms_map.items(), key=lambda kv: kv[0].lower())),
    }

    _ud_map = parsing_state["unparsable_dates"]
    unparsable_dates_block = {
        "count": sum(len(v) for v in _ud_map.values()),
        "systems_affected": len(_ud_map),
        "by_system": {sys: dates for sys, dates in sorted(_ud_map.items(), key=lambda kv: kv[0].lower())},
    }

    _swr_items = sorted(parsing_state["systems_with_residue"])
    systems_with_residue_block = {"count": len(_swr_items), "items": _swr_items}

    _dsq = parsing_state["disk_size_quotes"]
    disk_size_quotes_block = {
        "unique": len(_dsq),
        "distribution": {
            size: {"count": len(set(systems)), "systems": sorted(set(systems))}
            for size, systems in sorted(_dsq.items(), key=lambda kv: kv[0])
        },
    }

    header = build_summary_header(
        schema_id=SCHEMA_IDS["history"],
        schema_version=schema_version(SCHEMA_IDS["history"]),
        versions={
            "gh_version": history_version,
            "gh_date": history_date,
            "history_parser_version": tool_version("history_parser"),
        },
    )

    summary = {
        "header": header,
        "totals": {
            "systems_total": systems_count,
            "software_total": software_count,
            "entries_total": systems_count + software_count,
            "total_systems": systems_count,
            "total_software": software_count,
            "total_entries": systems_count + software_count,
            "systems_with_ports": systems_with_ports,
            "systems_with_aliases": systems_with_aliases,
            "port_lines_parsed": total_port_lines_all,
            "publisher_count_unique": len(parsing_state["publishers_found"]),
            "platform_count_unique": len(platforms_found_summary),
            "model_count_unique": len(parsing_state["models_found"].keys()),
            "additional_tag_count_unique": len(_tags_map),
            "ports_with_comments": parsing_state["ports_with_comments"],
            "systems_with_port_overview": len(overviews_map),
        },
        "found": {
            "section_headings_found": section_headings_block,
            "platform_categories_found": platform_categories_block,
            "platforms_found": summary_platforms_block,
            "publishers_found": publishers_block,
            "titles_found": titles_block,
            "region_codes": region_codes_block,
            "models_found": models_block,
            "comments_found": comments_block,
            "additional_tags_found": additional_tags_block,
            "disk_size_quotes": disk_size_quotes_block,
            "port_overview_texts": port_overview_block,
        },
        "anomalies": {
            "unexpected_platform_categories": unexpected_platform_categories_block,
            "odd_number_of_quotes": odd_number_of_quotes_block,
            "odd_number_of_brackets": odd_number_of_brackets_block,
            "ports_missing_subheadings": ports_missing_subheadings_block,
            "platform_banners": {
                "count": parsing_state["platform_banner_total"],
                "systems_affected": len(parsing_state["platform_banners_by_system"]),
                "by_system": {
                    sys: {"count": sum(counter.values()), "banners": dict(counter)}
                    for sys, counter in sorted(parsing_state["platform_banners_by_system"].items())
                },
            },
            "null_platform_ports": {
                "count": parsing_state["null_platform_ports_total"],
                "systems_affected": len(parsing_state["null_platform_ports_by_system"]),
                "by_system": dict(
                    sorted(
                        parsing_state["null_platform_ports_by_system"].items(),
                        key=lambda kv: (-kv[1], kv[0]),
                    )
                ),
                "by_system_lines": {k: v for k, v in parsing_state["null_platform_examples"].items()},
            },
        },
        "residue_flags": {
            "unparsable_dates": unparsable_dates_block,
            "systems_with_residue": systems_with_residue_block,
        },
    }
    return summary
