"""
MAME XML → canonical JSON orchestrator (stage: mame)

This module streams the full MAME XML and delegates all extraction/normalisation to
focused utils, then writes:
  - data/releases/<ver>/outputs/mame_machines.json            (canonical per-machine records; unfiltered)
  - data/releases/<ver>/summaries/mame_parsing_summary.json   (totals-only summary with distributions)
  - data/releases/<ver>/outputs/mame_parent_index.json        (parent→clones + reverse map)

Notes
-----
- No selection or filtering occurs here; downstream joins/selection happen in the
  transform pipeline.
- Text-field convention: missing text becomes "", but 'description' currently preserves
  None to match historic outputs (revisit in a later logic pass).
- Booleans in machine attributes are represented as "yes"/"no" strings.
- Stamped for reproducibility: stage uses data/releases/<ver>/.stamps/mame.json and includes
  the XML path as an input.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Dict
import zipfile
import hashlib, json, datetime


from mht.utils.config import LOG_LEVEL
from mht.utils.logger import setup_logger, maybe_log_progress
from mht.utils.stamps import save_stamp, stage_is_fresh
from mht.utils.paths import (
    mame_machines_path,
    mame_xml_path,
    parent_index_path,
    mame_summary_path,
    #ENCODINGS_JSON,   # temp shim
    encodings_cache_path,
    stamps_dir,
    archives_dir, active_version,    
)
from mht.utils.io import write_json
from mht.utils.mame_xml import (
    int_or_none, capture_root_attrs,
    get_machine_header, get_core_text_fields, iter_mame_events
)
# Backwards-compat for older tests that import _int_or_none from this module
_int_or_none = int_or_none
from mht.utils.displays import extract_displays_for_parser, extend_examples_capped
from mht.utils.controls import extract_controls_for_parser, extract_players_bucket
from mht.utils.chips import extract_chips_for_parser
from mht.utils.roms import rom_count_and_bytes
from mht.utils.media import disk_required_and_regions, summarise_device_refs, extract_sound_channels, requires_samples_flag
from mht.utils.selection import build_parent_index
from mht.utils.summaries import (
    build_mame_summary,
    update_counters,
    update_totals,
)
from mht.utils.validator import check_mame_parse_invariants
from mht.utils.booleans import yesno_str
# Backwards-compat for older tests that import _yesno_str from this module
_yesno_str = yesno_str
from mht.utils.records import build_mame_machine_record
from mht.utils.strings import year_bucket_key, manufacturer_bucket_key
from mht.provenance.peek import find_mame_xml_member


log = setup_logger(log_level=LOG_LEVEL)
__all__ = ["parse_mame_xml"]

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
        "kind": kind,                        # e.g. 'mame_xml'
        "leaf": leaf,
        "encoding": rec.get("encoding") or "utf-8",
        "detected_via": rec.get("detected_via"),
        "zip_archive": rec.get("zip_archive"),
        "zip_member": rec.get("zip_member"),
        "zip_crc32": rec.get("zip_crc32"),
        "zip_size_bytes": rec.get("zip_size_bytes"),
        "xml_decl_encoding": rec.get("xml_decl_encoding"),
        "xml_bom": rec.get("xml_bom"),
        "version_hint": rec.get("xml_root_attrs") or {},   # {'build': '...', 'version': '...'}
    }


def parse_mame_xml(file_path: Path, encodings: dict[str, str], max_records: int = 0) -> bool:
    """
    Stream-parse a MAME XML file and emit canonical JSON, summary, and parent index.

    Parameters
    ----------
    file_path : Path
        Path to the MAME XML (e.g., mame.xml).
    encodings : dict[str, str]
        Mapping of input filenames to encodings; uses encodings["mame.xml"].
    max_records : int, optional
        If > 0, stop after writing at most this many machines (useful for smoke tests).

    Returns
    -------
    bool
        True on success or when the stage is up-to-date (stamp matched);
        False only on XML parse error or failed writes.

    Side effects
    ------------
    - Writes:
        * data/releases/<ver>/outputs/mame_machines.json
        * data/releases/<ver>/summaries/mame_parsing_summary.json
        * data/releases/<ver>/outputs/mame_parent_index.json
    - Maintains a stage stamp at data/releases/<ver>/.stamps/mame.json and skips work if fresh.
    - Logs progress every 5,000 machines and emits warnings for invariants via utils.validator.
    """
    start = time.perf_counter()
    log.info(
        f"Starting full MAME XML parsing: {file_path.name}"
        + (f" (max {max_records} records)" if max_records else " (no limit)")
    )

    # Inputs / encoding
    mame_encoding = encodings["mame.xml"]

    # Per-release context
    ver = active_version()
    arc = archives_dir(ver)
    enc_path = encodings_cache_path(ver)   # data/releases/<ver>/encodings.json

    # Prefer a staged MAME zip; fall back to extracted mame.xml if needed
    mame_zip = None
    for p in sorted(arc.glob("*.zip"), key=lambda x: x.name.lower()):
        if "mame" in p.name.lower():
            mame_zip = p
            break
    if mame_zip is None:
        mame_zip = next(iter(sorted(arc.glob("*.zip"))), None)

    primary_input = mame_zip if mame_zip else mame_xml_path(ver)

    # IMPORTANT: use the per-release encodings.json in the stamp inputs
    fresh, stamp_path, current_stamp = stage_is_fresh(
        "mame.json",
        schema_id="mht.stage.mame",
        tool="mame_parser",
        inputs=[primary_input, enc_path],
    )
    if fresh:
        log.info("MAME stage up-to-date (stamp matched) — skipping rebuild")
        return True

    # Root attributes (if present)
    mame_build = None
    mame_mameconfig = None

    # Totals
    total_machines = 0
    total_parents = 0
    total_clones = 0
    total_isbios = 0
    total_isdevice = 0
    total_ismechanical = 0
    total_requires_samples = 0

    # Distributions
    years_ctr = Counter()
    manuf_ctr = Counter()
    players_ctr = Counter()
    control_type_overall_ctr = Counter()
    control_ways_overall_ctr = Counter()
    control_ways2_overall_ctr = Counter()
    control_ways3_overall_ctr = Counter()
    control_buttons_overall_ctr = Counter()
    control_reqbuttons_overall_ctr = Counter()
    cpus_per_machine_ctr = Counter()
    sound_devices_per_machine_ctr = Counter()
    displays_per_machine_ctr = Counter()
    speakers_per_machine_ctr = Counter()
    sound_channels_per_machine_ctr = Counter()
    display_types_overall_ctr = Counter()
    display_tags_overall_ctr = Counter()
    disk_regions_overall_ctr = Counter()
    disk_media_platforms_per_machine_ctr = Counter()
    dropped_displays_total = 0
    dropped_displays_examples: list[dict[str, object]] = []

    # Examples per bucket for disk_media_platforms_per_machine
    disk_media_examples: Dict[str, list[str]] = {}

    machines_out: Dict[str, Dict[str, Any]] = {}


    # Parse
    try:
        # --- choose event source: extracted XML if present, else XML inside a ZIP ---
        def _event_source():
            # 1) Use extracted file if it exists
            if Path(file_path).is_file():
                # existing fast-path: yields (event, elem) from the plain XML file
                for e in iter_mame_events(file_path, mame_encoding):
                    yield e
                return

            # 2) Otherwise, look for a MAME ZIP in the release archives
            import zipfile
            from mht.utils.paths import archives_dir, active_version

            ver = active_version()
            arch_dir = archives_dir(ver)

            # Prefer “mame*.zip”, then fall back to any zip
            candidates = sorted(arch_dir.glob("mame*.zip")) + sorted(arch_dir.glob("*.zip"))
            if not candidates:
                raise FileNotFoundError(
                    f"No extracted {file_path.name} and no ZIP archives found in {arch_dir}"
                )

            # Try candidates until we find an XML inside that looks like MAME’s
            for zp in candidates:
                try:
                    with zipfile.ZipFile(zp) as zf:
                        # Heuristic: pick the first *.xml containing “mame” in the name; else first *.xml
                        members = zf.namelist()
                        pick = None
                        for name in members:
                            nl = name.lower()
                            if nl.endswith(".xml") and "mame" in nl:
                                pick = name
                                break
                        if not pick:
                            pick = next((n for n in members if n.lower().endswith(".xml")), None)
                        if not pick:
                            # Not a relevant archive; try next one
                            continue

                        # Stream-parse directly from the zip member (binary file-like)
                        with zf.open(pick, "r") as fh:
                            # ET.iterparse accepts a file-like; encoding is read from XML prolog
                            for event, elem in ET.iterparse(fh, events=("start", "end")):
                                yield (event, elem)
                        return  # done after yielding all events
                except zipfile.BadZipFile:
                    # Try next candidate
                    continue

            # If we drop through, nothing usable was found
            raise FileNotFoundError(
                f"Could not locate a MAME XML: neither {file_path} nor a usable *.zip in {arch_dir}"
            )

        for event, elem in _event_source():
        #for event, elem in iter_mame_events(file_path, mame_encoding):
            # Root attributes (build/mameconfig)
            b, mc = capture_root_attrs(event, elem)
            if b is not None or mc is not None:
                mame_build, mame_mameconfig = b, mc

            # Process one machine when its end tag arrives
            if event == "end" and elem.tag == "machine":
                mame_name = elem.attrib.get("name")
                if not mame_name:
                    elem.clear()
                    continue

                # --- header attributes (now via helper) ---
                hdr = get_machine_header(elem)
                cloneof = hdr["cloneof"]
                isbios = hdr["isbios"]
                isdevice = hdr["isdevice"]
                ismechanical = hdr["ismechanical"]
                sampleof = hdr["sampleof"]
                sourcefile = hdr["sourcefile"]

                # --- core text fields (now via helper) ---
                description, year_raw, manufacturer_raw = get_core_text_fields(elem)

                # --- bucketing for summary dists ---
                year_key = year_bucket_key(year_raw)
                manufacturer_key = manufacturer_bucket_key(manufacturer_raw)

                # --- input & players/controls (helpers already in use) ---
                input_el = elem.find("input")
                players_key, players_value = extract_players_bucket(input_el)
                controls_list, _ctrl_metrics = extract_controls_for_parser(input_el)
                for k, v in _ctrl_metrics["type_overall"].items():
                    control_type_overall_ctr[k] += v
                for k, v in _ctrl_metrics["ways_overall"].items():
                    control_ways_overall_ctr[k] += v
                for k, v in _ctrl_metrics["ways2_overall"].items():
                    control_ways2_overall_ctr[k] += v
                for k, v in _ctrl_metrics["ways3_overall"].items():
                    control_ways3_overall_ctr[k] += v
                for k, v in _ctrl_metrics["buttons_overall"].items():
                    control_buttons_overall_ctr[k] += v
                for k, v in _ctrl_metrics["reqbuttons_overall"].items():
                    control_reqbuttons_overall_ctr[k] += v

                # --- audio/sound channels (helper) ---
                sound_channels = extract_sound_channels(elem)

                # device_ref summary (helper already in use)
                device_ref_summary = summarise_device_refs(elem)

                # --- chips (helper) ---
                chips_list, cpu_count, audio_count = extract_chips_for_parser(elem)

                # --- displays (helper) ---
                displays_list, display_count, _disp_metrics = extract_displays_for_parser(elem, mame_name)
                for k, v in _disp_metrics["types_overall"].items():
                    display_types_overall_ctr[k] += v
                for k, v in _disp_metrics["tags_overall"].items():
                    display_tags_overall_ctr[k] += v
                dropped_displays_total += _disp_metrics["dropped_total"]
                extend_examples_capped(dropped_displays_examples, _disp_metrics["dropped_examples"], cap=10)

                # --- samples? (helper) ---
                req_samples = requires_samples_flag(elem, sampleof)

                # --- ROMs (helper) ---
                rom_count, rom_bytes_total = rom_count_and_bytes(elem)

                # --- disks (helper) ---
                disk_required, disk_regions, _regions_overall = disk_required_and_regions(elem)
                disk_media_platforms_count = len(disk_regions)

                # --- per-machine counters & examples ---
                update_counters(
                    year_key=year_key,
                    manufacturer_key=manufacturer_key,
                    players_key=players_key,
                    cpu_count=cpu_count,
                    audio_count=audio_count,
                    display_count=display_count,
                    sound_channels=sound_channels,
                    speaker_ref_count=device_ref_summary["speaker"],
                    disk_regions_overall_add=_regions_overall,
                    disk_media_platforms_count=disk_media_platforms_count,
                    mame_name=mame_name,
                    years_ctr=years_ctr,
                    manuf_ctr=manuf_ctr,
                    players_ctr=players_ctr,
                    cpus_per_machine_ctr=cpus_per_machine_ctr,
                    sound_devices_per_machine_ctr=sound_devices_per_machine_ctr,
                    displays_per_machine_ctr=displays_per_machine_ctr,
                    sound_channels_per_machine_ctr=sound_channels_per_machine_ctr,
                    speakers_per_machine_ctr=speakers_per_machine_ctr,
                    disk_regions_overall_ctr=disk_regions_overall_ctr,
                    disk_media_platforms_per_machine_ctr=disk_media_platforms_per_machine_ctr,
                    disk_media_examples=disk_media_examples,
                )

                # --- totals ---
                (
                    total_machines,
                    total_parents,
                    total_clones,
                    total_isbios,
                    total_isdevice,
                    total_ismechanical,
                    total_requires_samples,
                ) = update_totals(
                    total_machines,
                    total_parents,
                    total_clones,
                    total_isbios,
                    total_isdevice,
                    total_ismechanical,
                    total_requires_samples,
                    cloneof=cloneof,
                    isbios=isbios,
                    isdevice=isdevice,
                    ismechanical=ismechanical,
                    requires_samples=req_samples,
                )

                # --- outputs (unchanged shaping) ---
                year_out = (year_raw or "")
                manufacturer_out = (manufacturer_raw or "")

                machines_out[mame_name] = build_mame_machine_record(
                    description=description,
                    sourcefile=sourcefile,
                    cloneof=cloneof,
                    isbios=isbios,
                    isdevice=isdevice,
                    ismechanical=ismechanical,
                    year=year_out,
                    manufacturer=manufacturer_out,
                    rom_count=rom_count,
                    rom_bytes_total=rom_bytes_total,
                    disk_required=disk_required,
                    disk_regions=disk_regions,
                    disk_media_platforms_count=disk_media_platforms_count,
                    cpu_count=cpu_count,
                    sound_chip_count=audio_count,
                    chips=chips_list,
                    sound_channels=sound_channels,
                    device_ref_summary=device_ref_summary,
                    sampleof=sampleof,
                    display_count=display_count,
                    displays=displays_list,
                    players_value=players_value,
                    controls=controls_list,
                )

                # progress log
                maybe_log_progress(
                    log,
                    total_machines,
                    step=5000,
                    prefix="[mame_parser::parse_mame_xml]",
                    fmt="{prefix} Parsed {count:,} machines so far...",
                )

                # honour max_records
                if max_records and total_machines >= max_records:
                    elem.clear()
                    break

                # free memory for this <machine>
                elem.clear()

    except ET.ParseError as e:
        log.error(f"XML parse error while reading {file_path.name}: {e}")
        return False

    parse_seconds = time.perf_counter() - start

    # ----------------------------
    # Build summary
    # ----------------------------
    summary = build_mame_summary(
        total_machines=total_machines,
        total_parents=total_parents,
        total_clones=total_clones,
        total_isbios=total_isbios,
        total_isdevice=total_isdevice,
        total_ismechanical=total_ismechanical,
        total_requires_samples=total_requires_samples,
        years_ctr=years_ctr,
        manuf_ctr=manuf_ctr,
        players_ctr=players_ctr,
        control_type_overall_ctr=control_type_overall_ctr,
        control_ways_overall_ctr=control_ways_overall_ctr,
        control_ways2_overall_ctr=control_ways2_overall_ctr,
        control_ways3_overall_ctr=control_ways3_overall_ctr,
        control_buttons_overall_ctr=control_buttons_overall_ctr,
        control_reqbuttons_overall_ctr=control_reqbuttons_overall_ctr,
        cpus_per_machine_ctr=cpus_per_machine_ctr,
        sound_devices_per_machine_ctr=sound_devices_per_machine_ctr,
        displays_per_machine_ctr=displays_per_machine_ctr,
        display_types_overall_ctr=display_types_overall_ctr,
        display_tags_overall_ctr=display_tags_overall_ctr,
        sound_channels_per_machine_ctr=sound_channels_per_machine_ctr,
        speakers_per_machine_ctr=speakers_per_machine_ctr,
        disk_regions_overall_ctr=disk_regions_overall_ctr,
        disk_media_platforms_per_machine_ctr=disk_media_platforms_per_machine_ctr,
        disk_media_examples=disk_media_examples,
        dropped_displays_total=dropped_displays_total,
        dropped_displays_examples=dropped_displays_examples,
        mame_build=mame_build,
        mame_mameconfig=mame_mameconfig,
    )

    # ----------------------------
    # Invariants (warnings only)
    # ----------------------------
    check_mame_parse_invariants(
        log=log,
        log_prefix="[mame_parser::parse_mame_xml]",
        total_machines=total_machines,
        machines_out=machines_out,
        years_ctr=years_ctr,
        manuf_ctr=manuf_ctr,
        players_ctr=players_ctr,
        cpus_per_machine_ctr=cpus_per_machine_ctr,
        sound_devices_per_machine_ctr=sound_devices_per_machine_ctr,
        displays_per_machine_ctr=displays_per_machine_ctr,
        speakers_per_machine_ctr=speakers_per_machine_ctr,
        sound_channels_per_machine_ctr=sound_channels_per_machine_ctr,
        display_types_overall_ctr=display_types_overall_ctr,
        display_tags_overall_ctr=display_tags_overall_ctr,
        disk_media_platforms_per_machine_ctr=disk_media_platforms_per_machine_ctr,
        control_type_overall_ctr=control_type_overall_ctr,
        control_ways_overall_ctr=control_ways_overall_ctr,
        control_ways2_overall_ctr=control_ways2_overall_ctr,
        control_ways3_overall_ctr=control_ways3_overall_ctr,
        control_buttons_overall_ctr=control_buttons_overall_ctr,
        control_reqbuttons_overall_ctr=control_reqbuttons_overall_ctr,
    )

    # ----------------------------
    # Write outputs
    # ----------------------------
    #if not write_json(mame_machines_path(), {k: machines_out[k] for k in sorted(machines_out)}, sort_keys=False):
    if not write_json(mame_machines_path(), {k: machines_out[k] for k in sorted(machines_out)}, sort_keys=False):
        return False
    log.info(f"Wrote canonical machines: {mame_machines_path()}")

    #if not write_json(mame_summary_path(), summary, sort_keys=False):
    if not write_json(mame_summary_path(), summary, sort_keys=False):
        return False
    log.info(f"Wrote MAME totals summary: {mame_summary_path()}")

    parent_index = build_parent_index(machines_out)
    #if not write_json(parent_index_path(), parent_index):
    if not write_json(parent_index_path(), parent_index):
        return False
    log.info(
        f"Wrote {parent_index_path()} "
        f"({len(parent_index['parents'])} parents-with-clones, "
        f"{len(parent_index['child_to_parent'])} clones)"
    )

    log.info(f"MAME XML parsing completed in {parse_seconds:.2f} seconds")
    log.info(f"Invalid display rows dropped: {dropped_displays_total}")

    # --- Decide success purely by outputs on disk ---
    ms = mame_summary_path()
    mm = mame_machines_path()
    pi = parent_index_path()  # optional

    success = ms.exists() and mm.exists()

    if not success:
        log.error("MAME outputs not found (expected summary and machines JSON). Stamp not saved.")
        return False

    # --- Build and save enriched stamp (inputs_detail, outputs, stats) ---
    stamp_doc = dict(current_stamp)  # keep the freshness core intact

    enc_cache = _load_encodings_cache()
    inputs_detail = [_xml_input_from_cache(enc_cache, "mame.xml", kind="mame_xml")]

    outputs = []
    # summary meta
    if ms.exists():
        outputs.append(_file_meta(ms))
    # machines meta (+ record count)
    if mm.exists():
        mmeta = _file_meta(mm)
        try:
            with open(mm, "r", encoding="utf-8") as f:
                recs = json.load(f)
            mmeta["records"] = len(recs) if isinstance(recs, dict) else None
        except Exception:
            mmeta["records"] = None
        outputs.append(mmeta)
    # parent index meta (+ record count), if present
    if pi.exists():
        pmeta = _file_meta(pi)
        try:
            with open(pi, "r", encoding="utf-8") as f:
                idx = json.load(f) or {}
            pmeta["records"] = len(idx.get("parents", {})) if isinstance(idx, dict) else None
        except Exception:
            pmeta["records"] = None
        outputs.append(pmeta)

    # stats: lift from the summary you just wrote
    stats = {}
    try:
        with open(ms, "r", encoding="utf-8") as f:
            s = json.load(f) or {}
        t = s.get("totals", {}) or {}
        stats = {
            "total_machines":         t.get("total_machines"),
            "total_parents":          t.get("total_parents"),
            "total_clones":           t.get("total_clones"),
            "total_isbios":           t.get("total_isbios"),
            "total_isdevice":         t.get("total_isdevice"),
            "total_ismechanical":     t.get("total_ismechanical"),
            "total_requires_samples": t.get("total_requires_samples"),
        }
    except Exception:
        pass

    stamp_doc["created_utc"] = datetime.datetime.utcnow().isoformat() + "Z"
    stamp_doc["inputs_detail"] = inputs_detail
    stamp_doc["outputs"] = outputs
    stamp_doc["stats"] = stats

    save_stamp(stamp_path, stamp_doc)
    log.info("MAME parsing completed; stamp saved with ZIP/encoding inputs.")
    return True
