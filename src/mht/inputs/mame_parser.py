"""
Filename: mame_parser.py
Author: XtC

Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Purpose:
Parse the full MAME XML and write:
  - output/mame_machines.json              (canonical, unfiltered dump)
  - data/mame_parsing_summary.json         (totals-only summary)
  - output/mame_parent_index.json          (parent -> clones index + reverse map)

No classification or filtering is applied here. Downstream modules will handle
selection (using .ini metadata) and the join with Gaming-History.
"""

from __future__ import annotations

import datetime
import json
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Dict

from mht.utils.config import LOG_LEVEL
from mht.utils.logger import setup_logger, maybe_log_progress
from mht.utils.versions import SCHEMA_IDS, schema_version, tool_version
from mht.utils.stamps import make_stamp, load_stamp, save_stamp, is_fresh
from mht.utils.paths import (
    STAMPS_DIR,
    MAME_MACHINES_PATH,
    PARENT_INDEX_PATH,
    MAME_SUMMARY,
    ENCODINGS_JSON,
)
from mht.utils.headers import build_summary_header
from mht.utils.io import write_json
from mht.utils.mame_xml import (
    attr_text, attr_yesno_bool, element_text, int_or_none, 
    capture_root_attrs, get_machine_header, get_core_text_fields,
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
    bucket_key_int,
    sorted_numeric_keys_with_unknown_last,
    sorted_alpha_with_unknown_last,
    sort_numeric_str,
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


log = setup_logger(log_level=LOG_LEVEL)
__all__ = ["parse_mame_xml"]


def parse_mame_xml(file_path: Path, encodings: dict[str, str], max_records: int = 0) -> bool:
    """
    Parse the entire mame.xml and write:
      - output/mame_machines.json
      - data/mame_parsing_summary.json
      - output/mame_parent_index.json

    Returns:
        bool: True on success, False if XML parse error occurs.
    """
    start = time.perf_counter()
    log.info(
        f"Starting full MAME XML parsing: {file_path.name}"
        + (f" (max {max_records} records)" if max_records else " (no limit)")
    )

    # Inputs / encoding
    mame_encoding = encodings["mame.xml"]

    # Stage stamp (skip-unchanged)
    STAMPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp_path = STAMPS_DIR / "mame.json"
    current_stamp = make_stamp(
        schema_id="mht.stage.mame",
        tool_version=tool_version("mame_parser"),
        #inputs = [file_path],
        inputs = [file_path, ENCODINGS_JSON],
    )
    prev = load_stamp(stamp_path)
    if is_fresh(current_stamp, prev):
        log.info("MAME stage up-to-date (stamp matched) — skipping parse")
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
        with open(file_path, encoding=mame_encoding) as f:
            it = ET.iterparse(f, events=("start", "end"))
            current_machine = None

            for event, elem in it:
                #if event == "start" and elem.tag == "mame":
                #    mame_build = elem.attrib.get("build")
                #    mame_mameconfig = elem.attrib.get("mameconfig")
                b, mc = capture_root_attrs(event, elem)
                if b is not None or mc is not None:
                    mame_build, mame_mameconfig = b, mc

                if event == "start" and elem.tag == "machine":
                    current_machine = elem

                if event == "end" and elem.tag == "machine" and current_machine is elem:
                    mame_name = elem.attrib.get("name")
                    if not mame_name:
                        elem.clear()
                        current_machine = None
                        continue

                    #cloneof      = attr_text(elem, "cloneof")
                    #isbios       = yesno_str(attr_yesno_bool(elem, "isbios"))
                    #isdevice     = yesno_str(attr_yesno_bool(elem, "isdevice"))
                    #ismechanical = yesno_str(attr_yesno_bool(elem, "ismechanical"))
                    #sampleof     = attr_text(elem, "sampleof")
                    #sourcefile   = attr_text(elem, "sourcefile")
                    #romof        = attr_text(elem, "romof")  # Not sure if this is still used
                    hdr = get_machine_header(elem)
                    cloneof = hdr["cloneof"]
                    isbios = hdr["isbios"]
                    isdevice = hdr["isdevice"]
                    ismechanical = hdr["ismechanical"]
                    sampleof = hdr["sampleof"]
                    sourcefile = hdr["sourcefile"]
                    romof = hdr["romof"]

                    # CHILD FIELDS
                    #description      = element_text(elem, "description", default=None) or None
                    #year_raw         = element_text(elem, "year", default="")
                    #manufacturer_raw = element_text(elem, "manufacturer", default="")
                    description, year_raw, manufacturer_raw = get_core_text_fields(elem)

                    # normalised keys for dists
                    #year_key = "unknown"
                    #if year_raw and len(year_raw) == 4 and year_raw.isdigit():
                    #    year_key = year_raw
                    #manufacturer_key = manufacturer_raw if manufacturer_raw else "unknown"
                    #if manufacturer_key.strip().strip("-.,;:/()[]{}") == "":
                    #    manufacturer_key = "unknown"
                    year_key = year_bucket_key(year_raw)
                    manufacturer_key = manufacturer_bucket_key(manufacturer_raw)

                    # INPUT - Players
                    input_el = elem.find("input")
                    players_key, players_value = extract_players_bucket(input_el)

                    # INPUT - Controls
                    controls_list, _ctrl_metrics = extract_controls_for_parser(input_el)
                    # Merge control metrics into your existing overall counters
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

                    # SOUND
                    sound_channels = extract_sound_channels(elem)
                    #sound_channels = None
                    #sound_el = elem.find("sound")
                    #if sound_el is not None:
                    #    channels_attr = (sound_el.attrib.get("channels") or "").strip()
                    #    sound_channels = _int_or_none(sound_el.attrib.get("channels"))
                    #sound_channels_per_machine_ctr[bucket_key_int(sound_channels)] += 1

                    # DEVICE REFS (samples/speaker)
                    device_ref_summary = summarise_device_refs(elem)
                    #speakers_per_machine_ctr[str(device_ref_summary["speaker"])] += 1
                    #speakers_per_machine_ctr[bucket_key_int(device_ref_summary["speaker"])] += 1

                    # CHIPS
                    chips_list, cpu_count, audio_count = extract_chips_for_parser(elem)

                    # DISPLAYS
                    displays_list, display_count, _disp_metrics = extract_displays_for_parser(elem, mame_name)

                    # Merge display metrics into the existing overall counters and dropped stats
                    for k, v in _disp_metrics["types_overall"].items():
                        display_types_overall_ctr[k] += v
                    for k, v in _disp_metrics["tags_overall"].items():
                        display_tags_overall_ctr[k] += v

                    dropped_displays_total += _disp_metrics["dropped_total"]
                    if _disp_metrics["dropped_examples"]:
                        # Keep your original cap of 10 total examples
                        #remaining = max(0, 10 - len(dropped_displays_examples))
                        #if remaining:
                        #    dropped_displays_examples.extend(_disp_metrics["dropped_examples"][:remaining])
                        extend_examples_capped(dropped_displays_examples, _disp_metrics["dropped_examples"], cap=10)

                    # SAMPLES flags
                    #sample_children = elem.findall("sample")
                    #requires_samples = bool(sampleof or sample_children)
                    #if requires_samples:
                    #    total_requires_samples += 1
                    #if requires_samples_flag(elem, sampleof):
                    #    total_requires_samples += 1

                    # requires-samples (unchanged logic, just capture the bool once)
                    req_samples = requires_samples_flag(elem, sampleof)

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

                    #if (total_machines % 5000) == 0:
                    #    log.info(f"[mame_parser::parse_mame_xml] Parsed {total_machines:,} machines so far...")
                    maybe_log_progress(
                        log,
                        total_machines,
                        step=5000,
                        prefix="[mame_parser::parse_mame_xml]",
                        fmt="{prefix} Parsed {count:,} machines so far...",
                    )

                    # ROMS
                    rom_count, rom_bytes_total = rom_count_and_bytes(elem)

                    # DISKS (regions only)
                    disk_required, disk_regions, _regions_overall = disk_required_and_regions(elem)
                    # Preserve the original per-disk region counting behaviour
                    #for k, v in _regions_overall.items():
                    #    disk_regions_overall_ctr[k] += v

                    disk_media_platforms_count = len(disk_regions)
                    #disk_media_platforms_per_machine_ctr[str(disk_media_platforms_count)] += 1
                    #disk_media_platforms_per_machine_ctr[bucket_key_int(disk_media_platforms_count)] += 1
                    #examples = disk_media_examples.setdefault(str(disk_media_platforms_count), [])
                    #if len(examples) < 5:
                    #    examples.append(mame_name)

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

                    # Totals
                    #total_machines += 1
                    #if (total_machines % 5000) == 0:
                    #    log.info(f"[mame_parser::parse_mame_xml] Parsed {total_machines:,} machines so far...")

                    #if cloneof:
                    #    total_clones += 1
                    #else:
                    #    total_parents += 1
                    #if isbios == "yes":
                    #    total_isbios += 1
                    #if isdevice == "yes":
                    #    total_isdevice += 1
                    #if ismechanical == "yes":
                    #    total_ismechanical += 1

                    #years_ctr[year_key] += 1
                    #manuf_ctr[manufacturer_key] += 1
                    #players_ctr[players_key] += 1
                    #cpus_per_machine_ctr[str(cpu_count)] += 1
                    #cpus_per_machine_ctr[bucket_key_int(cpu_count)] += 1
                    #sound_devices_per_machine_ctr[str(audio_count)] += 1
                    #sound_devices_per_machine_ctr[bucket_key_int(audio_count)] += 1
                    #displays_per_machine_ctr[str(display_count)] += 1
                    #displays_per_machine_ctr[bucket_key_int(display_count)] += 1

                    # after computing year_raw / manufacturer_raw:
                    year_out         = (year_raw or "")
                    manufacturer_out = (manufacturer_raw or "")

                    # Per-machine record
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
                        players_value=players_value,   # from extract_players_bucket
                        controls=controls_list,
                    )

                    if max_records and total_machines >= max_records:
                        elem.clear()
                        break

                    elem.clear()
                    current_machine = None

    except ET.ParseError as e:
        log.error(f"XML parse error while reading {file_path.name}: {e}")
        return False

    parse_seconds = time.perf_counter() - start
    #generated_at_utc = datetime.datetime.utcnow().isoformat() + "Z"


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
    if not write_json(MAME_MACHINES_PATH, {k: machines_out[k] for k in sorted(machines_out)}, sort_keys=False):
        return False
    log.info(f"Wrote canonical machines: {MAME_MACHINES_PATH}")

    if not write_json(MAME_SUMMARY, summary):  # summaries fine with sorted keys (default)
        return False
    log.info(f"Wrote MAME totals summary: {MAME_SUMMARY}")

    parent_index = build_parent_index(machines_out)
    if not write_json(PARENT_INDEX_PATH, parent_index):
        return False
    log.info(
        f"Wrote {PARENT_INDEX_PATH} "
        f"({len(parent_index['parents'])} parents-with-clones, "
        f"{len(parent_index['child_to_parent'])} clones)"
    )
    
    # All good → persist the stamp
    save_stamp(stamp_path, current_stamp)

    log.info(f"MAME XML parsing completed in {parse_seconds:.2f} seconds")
    log.info(f"Invalid display rows dropped: {dropped_displays_total}")
    return True
