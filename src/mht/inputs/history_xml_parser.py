"""
Gaming-History XML → structured JSON orchestrator (stage: history) — ZIP-only

Streams `history.xml` from the release ZIP and delegates work to focused helpers:
- Section segmentation, PORTS parsing (with banners/inheritance)
- Per-system record assembly
- Totals/distributions summary and invariants
- TRIVIA: emits gh_system_trivia.json with sections_raw and sections_blocks (with suppressions applied)
- Skips sections fully removed by suppression and records them for auditing

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
    gh_system_trivia_path,
)
from mht.utils.io import write_json, file_meta
from mht.inputs.history_constants import KNOWN_PLATFORMS
from mht.inputs.history_ports import extract_ports_section
from mht.inputs.history_text import parse_gh_id_from_contribute, extract_text_sections
from mht.inputs.history_summary import build_history_summary
from mht.utils.history_xml import capture_history_root_attrs, classify_entry
from mht.utils.validator import check_history_parse_invariants, validate_trivia_file_against_schema
from mht.utils.records import build_history_system_record, build_history_systems_sorted
from mht.utils.summaries import apply_ports_results, update_history_totals
from mht.utils.encoding_utils import load_encodings_cache
from mht.inputs.history_blocks import (
    classify_section_blocks, process_section_blocks, attach_list_preambles, 
    flag_suspect_hard_wraps, schema_sanitize_blocks,
)
from mht.inputs.history_suppress import apply_suppressions

__all__ = ["parse_history_entries"]

log = setup_logger(log_level=LOG_LEVEL)

# Allowed top-level keys per block type
_ALLOWED_BLOCK_KEYS_COMMON = {"type", "meta"}
_ALLOWED_BLOCK_KEYS_BY_TYPE = {
    "paragraph": _ALLOWED_BLOCK_KEYS_COMMON | {"text"},
    "bullet_list": _ALLOWED_BLOCK_KEYS_COMMON | {"items"},
    "numbered_list": _ALLOWED_BLOCK_KEYS_COMMON | {"items"},
    "pair": _ALLOWED_BLOCK_KEYS_COMMON | {"label", "value"},
    # if you emit other types later, add them here
}

# --- ZIP-only helpers ---------------------------------------------------------

def _pick_history_zip(version: str) -> Path:
    arc_dir = archives_dir(version)
    if not arc_dir.exists():
        raise FileNotFoundError(f"Archives folder missing: {arc_dir.as_posix()}")
    zips = sorted(arc_dir.glob("*.zip"), key=lambda p: p.name.lower())
    if not zips:
        raise FileNotFoundError(f"No .zip files found under {arc_dir.as_posix()}")
    prefer = [p for p in zips if "history" in p.name.lower()] or zips
    return prefer[0]

def _find_history_xml_member(zf: zipfile.ZipFile) -> str | None:
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

def _attach_trivia_section_blocks(
    *,
    entry_data: dict,
    primary: str,
    section_tag: str,          # e.g. "TRIVIA", "TECHNICAL", "UPDATES", etc. (canonical)
    raw_text: str,
    parsing_state: dict
) -> None:
    """
    Split `raw_text` into lines, apply suppressions, classify into blocks,
    and attach to entry_data['trivia']['sections'][section_tag] WITHOUT
    merging adjacent paragraphs. One paragraph == one block.
    """
    # 1) split to lines
    lines = (raw_text or "").splitlines()

    # 2) apply suppressions (section-aware)
    #    We use lower-case tag inside the suppressor ('technical', 'trivia', etc.)
    suppressed = apply_suppressions(section_tag.lower(), lines, primary, parsing_state)

    # 3) classify into blocks (one paragraph per block)
    blocks = process_section_blocks(
        primary=primary,
        section_tag=section_tag.lower(),
        lines=suppressed,
        parsing_state=parsing_state,
    )

    # 4) attach (no coalescing!)
    trivia = entry_data.setdefault("trivia", {})
    sections = trivia.setdefault("sections", {})
    sections[section_tag] = {"blocks": blocks}

# --- Main ---------------------------------------------------------------------

def parse_history_entries(file_path: Path, encoding: str) -> bool:
    start = time.perf_counter()
    ver = active_version()

    try:
        history_zip = _pick_history_zip(ver)
    except FileNotFoundError as e:
        log.error(str(e))
        return False

    enc_path = encodings_cache_path(ver)

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

        # Heading canonicalisation / anomalies
        "non_standard_sections": {},
        "banner_spacing_anomalies": {},

        # Block classification metrics
        "block_type_counts": Counter(),
        "unknown_blocks": {},

        # Suppressions summary
        "suppressions": {"counts": {}, "by_system": {}},

        # Sections removed entirely by suppression
        "fully_suppressed_sections": defaultdict(list),
    }

    total_entries = 0
    systems_count = 0
    software_count = 0
    systems_with_ports = 0
    systems_with_aliases = 0
    port_overview_count = 0
    total_port_lines_all = 0

    gh_systems: dict[str, dict] = {}
    gh_trivia: dict[str, dict] = {}

    try:
        with zipfile.ZipFile(history_zip) as zf:
            member = _find_history_xml_member(zf)
            if not member:
                log.error(f"No XML member found inside {history_zip.name}")
                return False

            with zf.open(member, "r") as zfh:
                wrapper = io.TextIOWrapper(zfh, encoding=encoding, errors="replace")

                for event, elem in ET.iterparse(wrapper, events=("start", "end")):
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
                        if sectioned:
                            # GH ID (from CONTRIBUTE)
                            if "CONTRIBUTE" in sectioned:
                                gh_id = parse_gh_id_from_contribute(sectioned["CONTRIBUTE"])
                                if gh_id is not None:
                                    entry_data["gh_id"] = gh_id

                            # --- TRIVIA (non-PORTS / non-CONTRIBUTE) with suppressions and provenance
                            raw_sections: dict[str, str] = {}
                            blocks_by_section: dict[str, list] = {}

                            for sec_name, sec_lines in sectioned.items():
                                if sec_name in ("PORTS", "CONTRIBUTE"):
                                    continue

                                tag = "overview" if sec_name == "OPENING" else sec_name.lower()
                                lines = sec_lines if isinstance(sec_lines, list) else str(sec_lines).splitlines()

                                # Apply suppressions AND capture line-level provenance
                                try:
                                    lines_filtered, prov = apply_suppressions(tag, lines, primary, parsing_state)
                                except Exception as e:
                                    debug_log(f"[history_parser::suppress] {primary}:{sec_name} suppression error: {e}")
                                    lines_filtered, prov = (lines, {"raw_line_indices": list(range(1, len(lines) + 1)), "line_suppressions": {}})

                                # If everything was removed → record full suppression and skip
                                if not any((ln or "").strip() for ln in lines_filtered):
                                    parsing_state["fully_suppressed_sections"][tag].append(primary)
                                    continue

                                # Raw strings for continuity
                                raw_sections[tag] = "\n".join(lines_filtered)

                                # Structured blocks with provenance injected
                                try:
                                    blocks = process_section_blocks(
                                        primary=primary,
                                        section_tag=tag,
                                        lines=lines_filtered,
                                        parsing_state=parsing_state,
                                        filtered_to_raw=prov.get("raw_line_indices"),
                                        per_line_suppressions=prov.get("line_suppressions"),
                                    )
                                except Exception as e:
                                    debug_log(f"[history_parser::blocks] {primary}:{sec_name} classification error: {e}")
                                    blocks = [{"type": "paragraph", "text": "\n".join(lines_filtered), "meta": {
                                        "system": primary, "section_tag": tag, "block_index": None,
                                        "raw_line_start": prov.get("raw_line_indices", [None])[0] if prov.get("raw_line_indices") else None,
                                        "raw_line_end": prov.get("raw_line_indices", [None])[-1] if prov.get("raw_line_indices") else None,
                                        "filtered_line_start": 0, "filtered_line_end": len(lines_filtered) - 1,
                                        "policy": {"per_line": False, "heuristic_per_line": False},
                                        "detectors": ["paragraph_fallback"], "suppressions": [], "text_hash": ""
                                    }}] if lines_filtered else []

                                # Finalise per-block meta: index/system/section_tag + sanitize
                                for idx, b in enumerate(blocks):
                                    m = b.setdefault("meta", {})
                                    m["block_index"] = idx
                                    m["system"] = primary
                                    m["section_tag"] = tag
                                    #b["meta"] = _sanitize_block_meta(m)

                                blocks = attach_list_preambles(blocks)
                                blocks = flag_suspect_hard_wraps(blocks)
                                blocks = schema_sanitize_blocks(blocks)   # <-- final guard
                                blocks_by_section[tag] = blocks

                            if raw_sections or blocks_by_section:
                                trivia_entry = {}
                                if "gh_id" in entry_data:
                                    trivia_entry["gh_id"] = entry_data["gh_id"]
                                if raw_sections:
                                    trivia_entry["sections_raw"] = raw_sections
                                if blocks_by_section:
                                    trivia_entry["sections"] = {k: {"blocks": v} for k, v in blocks_by_section.items()}
                                gh_trivia[primary] = trivia_entry

                            # --- PORTS (unchanged)
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

    systems_sorted = build_history_systems_sorted(gh_systems)
    if not write_json(gh_system_ports_path(), systems_sorted, sort_keys=False):
        return False
    log.info(f"Wrote {gh_system_ports_path()} ({len(systems_sorted)} systems)")

    trivia_sorted = dict(sorted(gh_trivia.items(), key=lambda kv: kv[0].lower()))

    if not write_json(gh_system_trivia_path(), trivia_sorted, sort_keys=False):
        return False
    log.info(f"Wrote {gh_system_trivia_path()} ({len(trivia_sorted)} systems)")

    # Commenting this out as it slows the Run down
    #validate_trivia_file_against_schema(gh_system_trivia_path(), warn_only=True)

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

    # --- Augment summary: full suppression audit (alphabetised) + sections_found.technical
    try:
        # 1) Suppressions (full detail) with by_system keys alphabetised (case-insensitive)
        sup = parsing_state.get("suppressions", {}) or {}
        by_system = sup.get("by_system", {}) or {}
        by_system_sorted = {k: by_system[k] for k in sorted(by_system.keys(), key=lambda s: s.lower())}
        summary["suppressions"] = {
            "counts": sup.get("counts", {}) or {},
            "by_system": by_system_sorted,
        }

        # 2) Sections fully removed by suppression — sort tags and system lists for readability
        fully = parsing_state.get("fully_suppressed_sections", {}) or {}
        fully_sorted = {}
        for tag in sorted(fully.keys(), key=lambda s: s.lower()):
            vals = fully[tag]
            # convert to list and sort case-insensitively
            vals_list = list(vals) if not isinstance(vals, list) else vals
            fully_sorted[tag] = sorted(vals_list, key=lambda s: s.lower())
        summary["fully_suppressed_sections"] = fully_sorted

        # 3) sections_found.technical — simple visibility and blocks count
        systems_with_technical = 0
        technical_blocks_total = 0
        for sys_name, entry in gh_trivia.items():
            secmap = entry.get("sections") or {}
            tech = secmap.get("technical")
            if isinstance(tech, dict):
                blocks = tech.get("blocks") or []
                if blocks:
                    systems_with_technical += 1
                    technical_blocks_total += len(blocks)

        sections_found = summary.get("sections_found", {}) or {}
        sections_found["technical"] = {
            "systems_count": systems_with_technical,
            "blocks_count": technical_blocks_total,
        }
        summary["sections_found"] = sections_found

        # 4) sections_found.overview — visibility and blocks count
        systems_with_overview = 0
        overview_blocks_total = 0
        for sys_name, entry in gh_trivia.items():
            secmap = entry.get("sections") or {}
            ov = secmap.get("overview")
            if isinstance(ov, dict):
                blocks = ov.get("blocks") or []
                if blocks:
                    systems_with_overview += 1
                    overview_blocks_total += len(blocks)

        sections_found["overview"] = {
            "systems_count": systems_with_overview,
            "blocks_count": overview_blocks_total,
        }
        summary["sections_found"] = sections_found

    except Exception as e:
        debug_log(f"[history_parser::summary] Failed to augment suppression/technical stats: {e}")

    if not write_json(history_summary_path(), summary, sort_keys=False):
        return False
    debug_log(f"Wrote parsing summary to {history_summary_path()}")

    log.info(f"History parsing completed in {time.perf_counter() - start:.2f} seconds")

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

    hs = history_summary_path()
    gh = gh_system_ports_path()
    tr = gh_system_trivia_path()
    success = hs.exists() and gh.exists() and tr.exists()
    if not success:
        log.error("History outputs not found. Stamp not saved.")
        return False

    stamp_doc = dict(current_stamp)

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
    if tr.exists():
        tmeta = file_meta(tr)
        try:
            with open(tr, "r", encoding="utf-8") as f:
                tr_map = json.load(f)
            tmeta["records"] = len(tr_map) if isinstance(tr_map, dict) else None
        except Exception:
            tmeta["records"] = None
        outputs.append(tmeta)

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
