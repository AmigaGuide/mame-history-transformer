"""
Gaming-History XML → structured JSON orchestrator (stage: history) — ZIP-only

Streams `history.xml` from the release ZIP and delegates work to focused helpers:
- Section segmentation, PORTS parsing (with banners/inheritance)
- Per-system record assembly
- Totals/distributions summary and invariants

Inputs (ZIP-only)
-----------------
- data/releases/<ver>/archives/history*.zip (must exist)
- encoding is taken from encodings.json and passed in by caller

Outputs
-------
- data/releases/<ver>/outputs/gh_system_ports.json
- data/releases/<ver>/outputs/gh_system_trivia.json
- data/releases/<ver>/summaries/history_parsing_summary.json
- data/releases/<ver>/.stamps/history.json

Notes
-----
- No selection/filtering beyond excluding non-arcade <software> entries.
- Progress is logged every 10,000 entries.
- Stage is stamped for reproducibility.
"""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET
import time
from collections import Counter, defaultdict
import zipfile
import io
import json, datetime

from mht.utils.config import LOG_LEVEL
from mht.utils.logger import setup_logger, debug_log, maybe_log_progress
from mht.utils.stamps import save_stamp, stage_is_fresh
from mht.utils.paths import (
    gh_system_ports_path, history_summary_path,
    archives_dir, active_version,
    encodings_cache_path,
)
from mht.utils.io import write_json, file_meta
from mht.inputs.history_constants import KNOWN_PLATFORMS
from mht.inputs.history_ports import extract_ports_section
from mht.inputs.history_text import parse_gh_id_from_contribute, extract_text_sections
from mht.inputs.history_summary import build_history_summary
from mht.utils.history_xml import capture_history_root_attrs, classify_entry
from mht.utils.validator import check_history_parse_invariants
from mht.utils.records import build_history_system_record, build_history_systems_sorted
from mht.utils.summaries import apply_ports_results, update_history_totals
from mht.utils.encoding_utils import load_encodings_cache
from mht.inputs.history_blocks import classify_section_blocks

__all__ = ["parse_history_entries"]

log = setup_logger(log_level=LOG_LEVEL)

# --- ZIP-only helpers ---------------------------------------------------------

def _pick_history_zip(version: str) -> Path:
    """Return the preferred History ZIP for this release, or raise FileNotFoundError."""
    arc_dir = archives_dir(version)
    if not arc_dir.exists():
        raise FileNotFoundError(f"Archives folder missing: {arc_dir.as_posix()}")
    zips = sorted(arc_dir.glob("*.zip"), key=lambda p: p.name.lower())
    if not zips:
        raise FileNotFoundError(f"No .zip files found under {arc_dir.as_posix()}")
    # Prefer names that contain 'history'
    prefer = [p for p in zips if "history" in p.name.lower()] or zips
    return prefer[0]

def _find_history_xml_member(zf: zipfile.ZipFile) -> str | None:
    """
    Locate the Gaming-History XML inside a GH zip.
    Prefer leaf named 'history.xml'; else fall back to largest *.xml.
    """
    names = zf.namelist()
    exact = [n for n in names if Path(n).name.lower() == "history.xml"]
    if exact:
        return exact[0]
    xmls = [n for n in names if n.lower().endswith(".xml")]
    if not xmls:
        return None
    sizes = {n: zf.getinfo(n).file_size for n in xmls}
    return max(xmls, key=lambda n: sizes.get(n, 0))

def _xml_input_from_cache(cache: dict, leaf: str, *, kind: str) -> dict:
    """
    Build a rich input block for 'history.xml' from encodings.json.
    """
    rec = cache.get(leaf) or {}
    return {
        "kind": kind,
        "leaf": leaf,
        "encoding": rec.get("encoding") or "utf-8",
        "ascii_only": bool(rec.get("ascii_only")),
        "detected_via": rec.get("detected_via"),
        "zip_archive": rec.get("zip_archive"),
        "zip_member": rec.get("zip_member"),
        "zip_crc32": rec.get("zip_crc32"),
        "zip_size_bytes": rec.get("zip_size_bytes"),
        "version_hint": rec.get("xml_header") or {},
    }

# --- Main ---------------------------------------------------------------------

def parse_history_entries(file_path: Path, encoding: str) -> bool:
    """
    ZIP-only streaming of `history.xml` and emit per-system PORTS JSON plus a summary.

    Parameters
    ----------
    file_path : Path
        Ignored in ZIP-only mode (kept for call-site compatibility).
    encoding : str
        Text encoding for the XML (used when wrapping the ZIP member stream).

    Returns
    -------
    bool
        True on success or when the stage is up-to-date (stamp matched);
        False only on ZIP/missing error, XML parse error, or failed writes.
    """
    start = time.perf_counter()
    ver = active_version()

    # Require a history ZIP; no fallback to extracted history.xml
    try:
        history_zip = _pick_history_zip(ver)
    except FileNotFoundError as e:
        log.error(str(e))
        return False

    enc_path = encodings_cache_path(ver)

    # Freshness: key strictly on the ZIP + encodings.json
    fresh, stamp_path, current_stamp = stage_is_fresh(
        "history.json",
        schema_id="mht.stage.history",
        tool="history_parser",
        inputs=[history_zip, enc_path],
    )
    if fresh:
        log.info("History stage up-to-date (stamp matched) — skipping rebuild")
        return True

    log.info(f"Parsing history.xml from zip: {history_zip.name} (encoding={encoding})")

    # State for summary & invariants
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
        # Heading normalisation / anomalies (populated by history_text.extract_text_sections)
        "non_standard_sections": {},   # {normalised_heading: {"count": int, "systems": set(), "mapped_to": str|None, "via": str|None}}        
        # Block classification metrics (populated by history_blocks.classify_section_blocks)
        "block_type_counts": Counter(),
        "unknown_blocks": {},        
    }

    total_entries = 0
    systems_count = 0
    software_count = 0
    systems_with_ports = 0
    systems_with_aliases = 0
    port_overview_count = 0
    total_port_lines_all = 0

    gh_systems: dict[str, dict] = {}
    # >>> NEW (TRIVIA scaffold): capture non-PORTS/non-CONTRIBUTE section text per system
    gh_trivia_systems: dict[str, dict] = {}

    # --- Stream XML from the ZIP ---------------------------------------------
    try:
        with zipfile.ZipFile(history_zip) as zf:
            member = _find_history_xml_member(zf)
            if not member:
                log.error(f"No XML member found inside {history_zip.name}")
                return False

            with zf.open(member, "r") as zfh:
                wrapper = io.TextIOWrapper(zfh, encoding=encoding, errors="replace")

                # Stream parse
                for event, elem in ET.iterparse(wrapper, events=("start", "end")):
                    # Root attributes
                    hdr = capture_history_root_attrs(event, elem)
                    if hdr is not None:
                        if history_version is None:
                            history_version = hdr.get("version")
                        if history_date is None:
                            history_date = hdr.get("date")
                        continue

                    if event == "end" and elem.tag == "entry":
                        kind, primary, aliases = classify_entry(elem)

                        total_entries, systems_count, software_count, systems_with_aliases = update_history_totals(
                            total_entries, systems_count, software_count, systems_with_aliases,
                            kind=kind, aliases=aliases,
                        )

                        maybe_log_progress(
                            log,
                            total_entries,
                            step=10000,
                            prefix="[history_parser::parse_history_entries]",
                            fmt="{prefix} Parsed {count:,} entries so far...",
                        )

                        if kind != "systems" or not primary:
                            elem.clear()
                            continue

                        entry_data = build_history_system_record(aliases=aliases)
                        
                        sectioned = extract_text_sections(elem, parsing_state, primary=primary)

                        # NEW: classify blocks inside each non-PORTS/non-CONTRIBUTE section for metrics
                        if sectioned:
                            for sec_name, sec_lines in sectioned.items():
                                if sec_name in ("PORTS", "CONTRIBUTE"):
                                    continue
                                try:
                                    lines = sec_lines if isinstance(sec_lines, list) else str(sec_lines).splitlines()
                                    classify_section_blocks(sec_name, lines, parsing_state)
                                except Exception as e:
                                    debug_log(f"[history_xml_parser::blocks] {primary}:{sec_name} classification error: {e}")
                                                                        
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

                            # >>> NEW (TRIVIA scaffold): everything except PORTS/CONTRIBUTE
                            if sectioned:                                                                        
                                raw_sections: dict[str, str] = {}
                                for sec_name, sec_lines in sectioned.items():
                                    if sec_name in ("PORTS", "CONTRIBUTE"):
                                        continue
                                    tag = "overview" if sec_name == "OPENING" else sec_name.lower()
                                    # join lists to a single string for the trivia scaffold
                                    if isinstance(sec_lines, list):
                                        raw_sections[tag] = "\n".join(sec_lines)
                                    else:
                                        raw_sections[tag] = str(sec_lines)                                                                                                                                                
                                gh_trivia_systems[primary] = {
                                    # Future: replace sections_raw with structured blocks (paragraphs/bullets/numbered/pairs/subheadings)
                                    "sections_raw": raw_sections
                                }

                        gh_systems[primary] = entry_data
                        elem.clear()

    except ET.ParseError as e:
        log.error(f"XML parse error inside {history_zip.name}: {e}")
        return False
    except zipfile.BadZipFile:
        log.error(f"Bad ZIP: {history_zip.as_posix()}")
        return False
    except FileNotFoundError as e:
        log.error(str(e))
        return False

    log.info(f"Parsed {total_entries} <entry> elements from {history_zip.name}")
    log.info(f"  - {systems_count} entries had <systems> (arcade-relevant)")
    log.info(f"  - {software_count} entries had <software> (non-arcade)")
    log.info(f"  - {port_overview_count} entries contained a port overview")

    # Write parsed per-system output (sorted)
    systems_sorted = build_history_systems_sorted(gh_systems)
    if not write_json(gh_system_ports_path(), systems_sorted, sort_keys=False):
        return False
    log.info(f"Wrote {gh_system_ports_path()} ({len(systems_sorted)} systems)")

    # >>> NEW (TRIVIA scaffold): write parallel trivia artefact next to gh_system_ports.json
    trivia_out = gh_system_ports_path().with_name("gh_system_trivia.json")
    trivia_sorted = build_history_systems_sorted(gh_trivia_systems)
    if not write_json(trivia_out, trivia_sorted, sort_keys=False):
        return False
    log.info(f"Wrote {trivia_out} ({len(trivia_sorted)} systems)")

    ns = parsing_state.get("non_standard_sections") or {}
    log.info(f"Non-standard section headings observed: {len(ns)} distinct; total offences={sum(r['count'] for r in ns.values())}")

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

    if not write_json(history_summary_path(), summary, sort_keys=False):
        return False
    debug_log(f"Wrote parsing summary to {history_summary_path()}")

    log.info(f"History parsing completed in {time.perf_counter() - start:.2f} seconds")

    # Cache tallies for checker
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

    # Decide success by outputs on disk
    hs = history_summary_path()
    gh = gh_system_ports_path()
    success = hs.exists() and gh.exists() and trivia_out.exists()   # >>> NEW (TRIVIA scaffold)
    if not success:
        log.error("History outputs not found. Stamp not saved.")
        return False

    # --- Enriched stamp (ZIP + encoding inputs, outputs, stats) --------------
    stamp_doc = dict(current_stamp)

    enc_path = encodings_cache_path(ver)
    enc_cache = load_encodings_cache(enc_path)

    inputs_detail = [_xml_input_from_cache(enc_cache, "history.xml", kind="history_xml")]

    outputs = []
    if hs.exists():
        outputs.append(file_meta(hs))
    if gh.exists():
        gmeta = file_meta(gh)
        try:
            with open(gh, "r", encoding="utf-8") as f:
                gh_map = json.load(f)
            gmeta["records"] = len(gh_map) if isinstance(gh_map, dict) else None
        except Exception:
            gmeta["records"] = None
        outputs.append(gmeta)

    # >>> NEW (TRIVIA scaffold): include trivia artefact in stamp outputs
    tr_meta = file_meta(trivia_out) if trivia_out.exists() else None
    if tr_meta:
        try:
            with open(trivia_out, "r", encoding="utf-8") as f:
                tr_map = json.load(f)
            tr_meta["records"] = len(tr_map) if isinstance(tr_map, dict) else None
        except Exception:
            tr_meta["records"] = None
        outputs.append(tr_meta)

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
            # >>> NEW (TRIVIA scaffold): surface basic coverage if present in summary
            "systems_with_text":    (s.get("sections", {}) or {}).get("systems_with_text"),
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
