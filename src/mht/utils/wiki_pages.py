from __future__ import annotations

from typing import Dict, List, Tuple, Any
from pathlib import Path
import datetime


from mht.utils.titles import build_redirect_sources, collapse_ws
from mht.utils.io import write_json


WIKI_PREFIX = "Lost In Translation/"

__all__ = ["compute_pages_and_redirects", "WIKI_PREFIX"]


def _pref(name: str, prefix: str) -> str:
    return f"{prefix}{name}"

def compute_pages_and_redirects(out_map: Dict[str, dict], prefix: str) -> dict:
    """
    Compute pages, page_names, redirects, and conflicts from the exported parents.
    - out_map: {machine -> record}, where record has "wiki_page_name" and optional "wiki_redirects"/"description"
    - prefix: e.g. "Lost In Translation/"

    Returns a dict with:
      {
        "pages": {machine: prefixed_page_name, ...},
        "page_names": [prefixed_page_name, ...],            # sorted
        "redirects": {prefixed_source: prefixed_target, ...},
        "conflicts": {
            "page_name_collisions": [{"page": <pref>, "machines": [...]}, ...],
            "redirect_conflicts":   [{"source": <pref>, "targets": [...], "machines": [...]}, ...],
        },
        "stats": { ... }  # counts
      }
    """
    # 1) page targets
    pairs: List[Tuple[str, str]] = []
    for machine, rec in out_map.items():
        wiki_name = (rec.get("wiki_page_name") or "").strip()
        pairs.append((_pref(wiki_name, prefix), machine))
    pairs.sort(key=lambda t: t[0].casefold())

    pages_map: Dict[str, str] = {machine: page for page, machine in pairs}

    page_to_machines: Dict[str, List[str]] = {}
    for page, machine in pairs:
        page_to_machines.setdefault(page, []).append(machine)

    page_names_list: List[str] = list(page_to_machines.keys())
    page_name_collisions: List[dict] = [
        {"page": page, "machines": sorted(machines)}
        for page, machines in page_to_machines.items()
        if len(machines) > 1
    ]

    # 2) redirects
    redirects_map: Dict[str, str] = {}
    redirect_conflicts: List[dict] = []
    sources_seen: Dict[str, str] = {}  # ci-key -> target page

    for machine, rec in out_map.items():
        target = pages_map[machine]
        wiki_name = rec.get("wiki_page_name") or ""
        sources = rec.get("wiki_redirects")

        # If not provided, derive from description
        if not sources:
            desc = rec.get("description") or {}
            sources = build_redirect_sources(desc, wiki_name)

        for src in (sources or []):
            pretty = collapse_ws(src)
            if not pretty:
                continue
            pref_src = _pref(pretty, prefix)
            key = pref_src.casefold()

            prev = sources_seen.get(key)
            if prev is None:
                sources_seen[key] = target
                redirects_map[pref_src] = target
            elif prev != target:
                # conflict: same source points to two different pages
                owners = [m for m, p in pages_map.items() if p in {prev, target}]
                redirect_conflicts.append({
                    "source": pref_src,
                    "targets": sorted({prev, target}),
                    "machines": sorted(set(owners)),
                })

    pages_map_sorted       = dict(sorted(pages_map.items(), key=lambda kv: kv[0].casefold()))
    redirects_map_sorted   = dict(sorted(redirects_map.items(), key=lambda kv: kv[0].casefold()))
    page_names_list_sorted = sorted(page_names_list, key=str.casefold)

    stats = {
        "parents_total":           len(out_map),
        "page_names_total":        len(page_names_list_sorted),
        "redirects_total":         len(redirects_map_sorted),
        "page_name_collisions":    len(page_name_collisions),
        "redirect_conflicts":      len(redirect_conflicts),
    }

    return {
        "pages": pages_map_sorted,
        "page_names": page_names_list_sorted,
        "redirects": redirects_map_sorted,
        "conflicts": {
            "page_name_collisions": page_name_collisions,
            "redirect_conflicts": redirect_conflicts,
        },
        "stats": stats,
    }

def write_pages_and_redirects(
    *,
    out_map: Dict[str, Dict[str, Any]],
    prefix: str,
    schema_id: str,
    schema_version: str,
    output_path: Path,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Compute page/redirect info from `out_map` and write the pages artefact.

    Returns
    -------
    (ok_written, pages_info)
    """
    pages_info = compute_pages_and_redirects(out_map, prefix)

    generated_at_iso = datetime.datetime.utcnow().isoformat() + "Z"
    doc = {
        "header": {
            "schema_id": schema_id,
            "schema_version": schema_version,
            "generated_at": generated_at_iso,
        },
        "prefix": prefix,
        "stats": pages_info["stats"],
        "pages": pages_info["pages"],
        "page_names": pages_info["page_names"],
        "redirects": pages_info["redirects"],
        "conflicts": pages_info["conflicts"],
    }
    ok = write_json(output_path, doc)
    return ok, pages_info
