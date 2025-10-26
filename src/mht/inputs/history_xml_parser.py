"""
Gaming-History XML → structured JSON orchestrator (stage: history)

Streams `history.xml` <entry> elements and delegates work to focused helpers:
- Section segmentation, PORTS parsing (with banners/inheritance)
- Per-system record assembly
- Totals/distributions summary and invariants

Inputs
------
- history.xml (Gaming-History export), with encoding provided by caller.
- Optional CONTRIBUTE lines containing a gh_id in the form 'id=<int>'.

Outputs
-------
- data/releases/<ver>/outputs/gh_system_ports.json         (per-system structured PORTS data, sorted)
- data/releases/<ver>/summaries/history_parsing_summary.json   (totals, distributions, anomalies, audits)

Notes
-----
- No selection/filtering beyond excluding non-arcade <software> entries.
- Progress is logged every 10,000 entries.
- Stage is stamped for reproducibility in data/releases/<ver>/.stamps/history.json.
"""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET
import time
from collections import Counter, defaultdict
import zipfile
import io
import hashlib, json, datetime
from typing import Any

from mht.utils.config import LOG_LEVEL
from mht.utils.logger import setup_logger, debug_log, maybe_log_progress
from mht.utils.stamps import save_stamp, stage_is_fresh
from mht.utils.paths import (
    gh_system_ports_path,
    history_summary_path,
    history_xml_path,
    #ENCODINGS_JSON,   # temp shim
    stamps_dir, archives_dir, active_version, encodings_cache_path,
)
from mht.utils.io import write_json
from mht.inputs.history_constants import KNOWN_PLATFORMS
from mht.inputs.history_ports import extract_ports_section
from mht.inputs.history_text import parse_gh_id_from_contribute, extract_text_sections
from mht.inputs.history_summary import build_history_summary
from mht.utils.history_xml import (
    iter_history_events,
    capture_history_root_attrs,
    classify_entry,
)
from mht.utils.validator import check_history_parse_invariants
from mht.utils.records import build_history_system_record, build_history_systems_sorted
from mht.utils.summaries import apply_ports_results, update_history_totals
from mht.provenance.peek import find_history_xml_member


__all__ = ["parse_history_entries"]

log = setup_logger(log_level=LOG_LEVEL)


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def _file_meta(p: Path) -> dict[str, Any]:
    st = p.stat()
    return {
        "path": p.as_posix(),
        "size_bytes": int(st.st_size),
        "modified_utc": datetime.datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z",
        "sha256": _sha256_file(p),
    }

def _load_encodings_cache() -> dict[str, Any]:
    try:
        with open(ENCODINGS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _xml_input_from_cache(cache: dict[str, Any], leaf: str, kind: str) -> dict[str, Any]:
    rec = cache.get(leaf) or {}
    return {
        "kind": kind,                        # e.g. 'history_xml'
        "leaf": leaf,                        # expected: 'history.xml'
        "encoding": rec.get("encoding") or "utf-8",
        "detected_via": rec.get("detected_via"),
        "zip_archive": rec.get("zip_archive"),
        "zip_member": rec.get("zip_member"),
        "zip_crc32": rec.get("zip_crc32"),
        "zip_size_bytes": rec.get("zip_size_bytes"),
        "xml_decl_encoding": rec.get("xml_decl_encoding"),
        "xml_bom": rec.get("xml_bom"),
        "version_hint": rec.get("xml_root_attrs") or {},   # {'version': '2.80', ...}
    }


def parse_history_entries(file_path: Path, encoding: str) -> bool:
    """
    Stream-parse `history.xml` and emit per-system PORTS JSON plus a summary.

    Parameters
    ----------
    file_path : Path
        Path to the Gaming-History XML (history.xml).
    encoding : str
        Text encoding for the XML, supplied by the caller.

    Returns
    -------
    bool
        True on success or when the stage is up-to-date (stamp matched);
        False only on XML parse error or failed writes.

    Side effects
    ------------
    - Writes:
        * data/releases/<ver>/outputs/gh_system_ports.json
        * data/releases/<ver>/summaries/history_parsing_summary.json
    - Maintains a stage stamp at data/releases/<ver>/.stamps/history.json.
    - Logs progress every 10,000 entries.
    - Emits warnings-only invariants via utils.validator.
    """
    start = time.perf_counter()

    # --- ZIP-aware freshness (skip if unchanged) ---
    ver = active_version()
    arc = archives_dir(ver)
    enc_path = encodings_cache_path(ver)  # data/releases/<ver>/encodings.json

    # Prefer a 'history*.zip'; else first .zip; else fall back to extracted history.xml
    history_zip = None
    for p in sorted(arc.glob("*.zip"), key=lambda x: x.name.lower()):
        if "history" in p.name.lower():
            history_zip = p
            break
    if history_zip is None:
        history_zip = next(iter(sorted(arc.glob("*.zip"))), None)

    primary_input = history_zip if history_zip else history_xml_path(ver)

    fresh, stamp_path, current_stamp = stage_is_fresh(
        "history.json",
        schema_id="mht.stage.history",
        tool="history_parser",
        inputs=[primary_input, enc_path],
    )

    if fresh:
        log.info("History stage up-to-date (stamp matched) — skipping rebuild")
        return True

    log.info(f"Parsing history.xml entries from: {file_path.name} using {encoding}")

    # Read <history> root attributes for the summary header
    history_version, history_date = None, None

    parsing_state = {
        "platforms_found": defaultdict(lambda: {"count": 0, "systems": []}),
        "ports_with_comments": 0,
        "unparsable_dates": defaultdict(list),
        "systems_with_residue": set(),
        "section_headings_found": Counter(),
        "platform_categories_found": Counter(),
        "unexpected_platform_categories": defaultdict(list),
        "publishers_found": defaultdict(lambda: {"count": 0, "systems": []}),
        "publisher_indicators_found": {"released_by": 0, "by": 0, "other_after_date": 0, "none": 0},
        "odd_quotes": defaultdict(list),
        "odd_brackets": defaultdict(list),
        "titles_found": set(),
        "region_codes": Counter(),
        "models_found": defaultdict(list),
        "comments_found": defaultdict(list),
        "additional_tags_found": defaultdict(list),
        "systems_with_port_overview": {},
        "platform_banner_total": 0,
        "platform_banners_by_system": defaultdict(Counter),
        "null_platform_ports_total": 0,
        "null_platform_ports_by_system": Counter(),
        "null_platform_examples": defaultdict(list),
        "disk_size_quotes": defaultdict(list),
    }

    # Totals
    total_entries = 0
    systems_count = 0
    software_count = 0
    systems_with_ports = 0
    systems_with_aliases = 0
    port_overview_count = 0
    total_port_lines_all = 0

    gh_systems: dict[str, dict] = {}
    
    # --- Event source that supports ZIP-only setups ---------------------------
    def _event_source():
        # 1) If the extracted XML exists, use the standard iterator.
        if file_path.exists():
            for ev in iter_history_events(file_path, encoding):
                yield ev
            return

        # 2) Fallback: look for history*.zip in releases/<ver>/archives and stream its XML.
        try:
            ver = active_version()
        except Exception:
            ver = None

        if ver:
            adir = archives_dir(ver)
            if adir.exists():
                for zp in sorted(adir.glob("history*.zip")):
                    try:
                        with zipfile.ZipFile(zp) as zf:
                            # Prefer entry literally named 'history.xml'; else first *.xml
                            members = zf.namelist()
                            choice = None
                            for name in members:
                                if name.lower().endswith(".xml"):
                                    choice = name
                                    if Path(name).name.lower() == "history.xml":
                                        break
                            if not choice:
                                continue
                            with zf.open(choice, "r") as zfh:
                                wrapper = io.TextIOWrapper(zfh, encoding=encoding, errors="replace")
                                for ev in ET.iterparse(wrapper, events=("start", "end")):
                                    yield ev
                            return  # streamed one archive; stop
                    except zipfile.BadZipFile:
                        continue

        # 3) Nothing worked: surface a clear error
        raise FileNotFoundError(
            f"history.xml not found: {file_path} (and no usable history*.zip in archives)"
        )

    # --- Streaming parse ------------------------------------------------------
    try:
        for event, elem in _event_source():
            # Capture <history> root attributes on the start event (once)
            hdr = capture_history_root_attrs(event, elem)
            if hdr is not None:
                if history_version is None:
                    history_version = hdr.get("version")
                if history_date is None:
                    history_date = hdr.get("date")
                continue

            # Process each <entry> at its end tag
            if event == "end" and elem.tag == "entry":
                # Classify first so we know which counters to bump
                kind, primary, aliases = classify_entry(elem)

                # Totals update (replaces manual increments)
                total_entries, systems_count, software_count, systems_with_aliases = update_history_totals(
                    total_entries,
                    systems_count,
                    software_count,
                    systems_with_aliases,
                    kind=kind,
                    aliases=aliases,
                )

                # Progress log using the updated total_entries
                maybe_log_progress(
                    log,
                    total_entries,
                    step=10000,
                    prefix="[history_parser::parse_history_entries]",
                    fmt="{prefix} Parsed {count:,} entries so far...",
                )

                if kind == "systems":
                    if not primary:
                        elem.clear()
                        continue
                    entry_data = build_history_system_record(aliases=aliases)

                elif kind == "software":
                    elem.clear()
                    continue

                else:
                    elem.clear()
                    continue

                sectioned = extract_text_sections(elem, parsing_state)
                if sectioned:
                    if "CONTRIBUTE" in sectioned:
                        gh_id = parse_gh_id_from_contribute(sectioned["CONTRIBUTE"])
                        if gh_id is not None:
                            entry_data["gh_id"] = gh_id

                    if "PORTS" in sectioned:
                        overview, platform_counts, platform_ports, port_lines = extract_ports_section(
                            sectioned["PORTS"], primary, parsing_state
                        )
                        systems_with_ports, port_overview_count, total_port_lines_all, entry_data = apply_ports_results(
                            parsing_state=parsing_state,
                            primary=primary,
                            entry_data=entry_data,
                            overview=overview,
                            platform_counts=platform_counts,
                            platform_ports=platform_ports,
                            port_lines=port_lines,
                            systems_with_ports=systems_with_ports,
                            port_overview_count=port_overview_count,
                            total_port_lines_all=total_port_lines_all,
                        )

                gh_systems[primary] = entry_data

                # free memory for this <entry>
                elem.clear()

    except ET.ParseError as e:
        log.error(f"XML parse error in {file_path.name}: {e}")
        return False
    except FileNotFoundError as e:
        log.error(str(e))
        return False

    log.info(f"Parsed {total_entries} <entry> elements from history.xml")
    log.info(f"  - {systems_count} entries had <systems> (arcade-relevant)")
    log.info(f"  - {software_count} entries had <software> (non-arcade)")
    log.info(f"  - {port_overview_count} entries contained a port overview")

    # Write parsed per-system output (sorted)
    systems_sorted = build_history_systems_sorted(gh_systems)
    #if not write_json(gh_system_ports_path(), systems_sorted, sort_keys=False):  # preserve your explicit order
    if not write_json(gh_system_ports_path(), systems_sorted, sort_keys=False):
        return False
    log.info(f"Wrote {gh_system_ports_path()} ({len(systems_sorted)} systems)")

    summary = build_history_summary(
        history_version=history_version,
        history_date=history_date,
        parsing_state=parsing_state,
        systems_count=systems_count,
        software_count=software_count,
        systems_with_ports=systems_with_ports,
        systems_with_aliases=systems_with_aliases,
        total_port_lines_all=total_port_lines_all,
    )

    #if not write_json(history_summary_path(), summary, sort_keys=False):
    if not write_json(history_summary_path(), summary, sort_keys=False):
        return False
    debug_log(f"Wrote parsing summary to {history_summary_path()}")

    log.info(f"History parsing completed in {time.perf_counter() - start:.2f} seconds")

    # Cache some tallies for the checker (read-only convenience)
    parsing_state["total_port_lines_all"] = total_port_lines_all
    parsing_state["systems_with_ports_count"] = systems_with_ports
    parsing_state["port_overview_count"] = port_overview_count

    check_history_parse_invariants(
        log=log,
        systems_count=systems_count,
        software_count=software_count,
        total_entries=total_entries,
        gh_systems=gh_systems,
        parsing_state=parsing_state,
        KNOWN_PLATFORMS=KNOWN_PLATFORMS,
    )

    # --- Decide success purely by outputs on disk ---
    hs = history_summary_path()
    gh = gh_system_ports_path()

    success = hs.exists() and gh.exists()

    if not success:
        log.error("History outputs not found (expected history_parsing_summary.json and gh_system_ports.json). Stamp not saved.")
        return False

    # --- Build and save enriched stamp (inputs_detail, outputs, stats) ---
    stamp_doc = dict(current_stamp)  # keep the freshness core intact

    enc_cache = _load_encodings_cache()
    inputs_detail = [_xml_input_from_cache(enc_cache, "history.xml", kind="history_xml")]

    outputs = []
    # summary meta
    if hs.exists():
        outputs.append(_file_meta(hs))
    # gh_system_ports meta (+ record count)
    if gh.exists():
        gmeta = _file_meta(gh)
        try:
            with open(gh, "r", encoding="utf-8") as f:
                gh_map = json.load(f)
            gmeta["records"] = len(gh_map) if isinstance(gh_map, dict) else None
        except Exception:
            gmeta["records"] = None
        outputs.append(gmeta)

    # stats: lift from the summary you just wrote
    stats = {}
    try:
        with open(hs, "r", encoding="utf-8") as f:
            s = json.load(f) or {}
        totals = s.get("totals", {}) or {}
        systems_total  = totals.get("systems_total")
        software_total = totals.get("software_total") or 0
        entries_total  = (systems_total or 0) + (software_total or 0)
        stats = {
            "systems_total":        systems_total,
            "software_total":       software_total,
            "entries_total":        entries_total,
            "systems_with_ports":   totals.get("systems_with_ports"),
            "systems_with_aliases": totals.get("systems_with_aliases"),
            "port_lines_parsed":    totals.get("port_lines_parsed"),
            "ports_with_comments":  totals.get("ports_with_comments"),
        }
    except Exception:
        pass

    stamp_doc["created_utc"] = datetime.datetime.utcnow().isoformat() + "Z"
    stamp_doc["inputs_detail"] = inputs_detail
    stamp_doc["outputs"] = outputs
    stamp_doc["stats"] = stats

    save_stamp(stamp_path, stamp_doc)
    log.info("History parsing completed; stamp saved with ZIP/encoding inputs.")
    return True
