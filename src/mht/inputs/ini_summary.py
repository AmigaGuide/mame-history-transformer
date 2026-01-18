"""
INI summary builder for the History INI stage (pure).

Takes the parsed INI bundle (from load_ini_classifications) and assembles
data/ini_parsing_summary.json, including:
- per-file stats (encoding, version hints, section counts, duplicates)
- union/missing coverage across game_status/category/type
- a unified header with schema/tool versions

No file I/O or stamps here; callers handle writing and stamping.
"""

from __future__ import annotations

from typing import Dict, Set

from mht.utils.headers import build_summary_header
from mht.utils.versions import SCHEMA_IDS, schema_version, tool_version
from mht.utils.ini import (
    sorted_counts_from_listed,
    sorted_counts_from_unique_sets,
)


def build_ini_summary(parsed: Dict[str, dict], now_iso: str) -> dict:
    """
    Build the summary object for data/ini_parsing_summary.json from a parsed bundle.

    Parameters
    ----------
    parsed : dict
        Output of load_ini_classifications(): {
            "game_status": {...}, "category": {...}, "type": {...}
        }
    now_iso : str
        Timestamp (UTC, ISO8601 with 'Z') for header.generated_at.

    Returns
    -------
    dict
        The complete summary document (header + files + totals + errors).
    """
    files_block: Dict[str, dict] = {}
    errors: list[str] = []

    # Union of machine names across all INIs
    union_names: Set[str] = set()
    
    expected = ("game_status", "category", "type")

    for key in expected:
        info = parsed.get(key, {}) or {}
        ms: Dict[str, Set[str]] = info.get("machine_sections", {})
        slc: Dict[str, int]      = info.get("section_listed_counts", {})
        sus: Dict[str, Set[str]] = info.get("section_unique_sets", {})
        union_names |= set(ms.keys())

        # Prefer a reported filename if you add one later; otherwise keep key-based friendly names
        filename = info.get("filename") or key

        files_block[key] = {
            "filename": filename,
            "encoding": info.get("encoding", "utf-8"),
            "version": info.get("version", {}) or {},
            "entries_listed": info.get("entries_listed", 0),
            "entries_indexed": len(ms),
            "sections_total": len((slc or {}).keys() | (sus or {}).keys()),
            "section_counts_listed": sorted_counts_from_listed(slc or {}),
            "section_counts_unique": sorted_counts_from_unique_sets(sus or {}),
            "machines_with_multiple_sections": info.get("machines_with_multiple_sections", 0),
            "duplicate_assignments": info.get("duplicates_across_sections", 0),
        }

        # ZIP-only: missing means "not present in parsed bundle" OR placeholder shape.
        #if not info or not ms:
        #    errors.append(f"Missing INI data: {key}")

    coverage = {
        "unique_machine_names_union": len(union_names),
        "with_game_status": len((parsed.get("game_status", {}) or {}).get("machine_sections", {})),
        "missing_in_game_status": len(union_names) - len((parsed.get("game_status", {}) or {}).get("machine_sections", {})),
        "with_category": len((parsed.get("category", {}) or {}).get("machine_sections", {})),
        "missing_in_category": len(union_names) - len((parsed.get("category", {}) or {}).get("machine_sections", {})),
        "with_type": len((parsed.get("type", {}) or {}).get("machine_sections", {})),
        "missing_in_type": len(union_names) - len((parsed.get("type", {}) or {}).get("machine_sections", {})),
    }

    # Header versions (consensus if possible)
    header_versions: Dict[str, str] = {"ini_generated_at": now_iso}
    mame_versions = {
        (v or {}).get("mame_version")
        for v in (files_block[k]["version"] for k in files_block)
        if v and (v.get("mame_version"))
    }
    if len(mame_versions) == 1:
        header_versions["mame_xml_version"] = next(iter(mame_versions))
    mame_builds = {
        (v or {}).get("mame_build")
        for v in (files_block[k]["version"] for k in files_block)
        if v and (v.get("mame_build"))
    }
    
    if len(mame_builds) == 1 and len(mame_versions) == 1:
        v = next(iter(mame_versions))
        b = next(iter(mame_builds))
        header_versions["mame_build"] = f"{v} ({b})"

    header = build_summary_header(
        schema_id=SCHEMA_IDS["ini"],
        schema_version=schema_version(SCHEMA_IDS["ini"]),
        versions={**header_versions, "ini_summary_version": tool_version("ini_summary")},
        generated_at=now_iso,
    )

    expected = ("game_status", "category", "type")

    prov_inputs = []
    for key in expected:
        info = parsed.get(key, {}) or {}
        
        v = (info.get("version") or {}).get("mame_version")
        b = (info.get("version") or {}).get("mame_build")

        declared_build = None
        if v and b:
            declared_build = f"{v} ({b})"
        elif b:
            declared_build = b

        prov_inputs.append({
            "name": info.get("zip_member") or info.get("filename") or key,
            "declared_mame_version": v,
            "declared_mame_build": declared_build,
            "zip_member_modified": info.get("zip_member_modified"),
            "zip_archive": info.get("zip_archive"),
            "zip_member": info.get("zip_member"),
            "encoding": info.get("encoding", "utf-8"),
        })

    summary = {
        "header": header,
        "provenance": {"inputs": prov_inputs},        
        "ini": {
            "generated_at": now_iso,
            "files": files_block,
        },
        "totals": coverage,
        "errors": errors,
    }
    return summary
