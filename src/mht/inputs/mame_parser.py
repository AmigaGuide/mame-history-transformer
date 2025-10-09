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
from mht.utils.logger import setup_logger
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
from mht.utils.mame_xml import attr_text, attr_int, attr_yesno_bool, safe_int, element_text
from mht.utils.mame_fields import normalise_year, normalise_manufacturer
from mht.utils.displays import extract_displays_for_parser
from mht.utils.controls import extract_controls_for_parser
from mht.utils.chips import extract_chips_for_parser
from mht.utils.roms import rom_count_and_bytes
from mht.utils.media import disk_required_and_regions, summarise_device_refs
from mht.utils.selection import build_parent_index


log = setup_logger(log_level=LOG_LEVEL)

__all__ = ["parse_mame_xml"]

def _int_or_none(s: str | None) -> int | None:
    """
    Parse an integer or return None when value is empty/invalid.

    Notes
    -----
    Keeps 'unknown' distinct from 0 (important for summaries/buckets).
    """           
    s = (s or "").strip()
    return int(s) if s.isdigit() else None

def _bucket_key_int(v: int | None) -> str:
    """
    Convert an optional int to a stable bucket key for counters.

    Examples
    --------
    >>> _bucket_key_int(2)
    '2'
    >>> _bucket_key_int(None)
    'unknown'
    """            
    return str(v) if v is not None else "unknown"

def _yesno_str(flag: bool) -> str:
    """
    Map a boolean to the schema-required 'yes'/'no' string.

    Parameters
    ----------
    flag
        Input boolean.

    Returns
    -------
    str
        'yes' if True, else 'no'.
    """           
    return "yes" if flag else "no"

def _sorted_numeric_keys_with_unknown_last(counter: Dict[str, int]) -> Dict[str, int]:
    """Numeric ascending; non-digits rolled into 'other'; 'unknown' last."""
    numeric = []
    unknown = None
    other = 0
    for k, v in counter.items():
        if k == "unknown":
            unknown = v
        elif k.isdigit():
            numeric.append((int(k), v))
        else:
            other += v
    numeric.sort(key=lambda t: t[0])
    out: Dict[str, int] = {str(k): v for k, v in numeric}
    if other:
        out["other"] = other
    if unknown is not None:
        out["unknown"] = unknown
    return out


def _sorted_alpha_with_unknown_last(counter: Dict[str, int]) -> Dict[str, int]:
    """Case-insensitive A–Z; 'unknown' last."""
    items = [(k, v) for k, v in counter.items() if k != "unknown"]
    items.sort(key=lambda kv: kv[0].lower())
    out = {k: v for k, v in items}
    if "unknown" in counter:
        out["unknown"] = counter["unknown"]
    return out


def _sort_numeric_str(counter: Dict[str, int]) -> Dict[str, int]:
    """Numeric-string keys ascending; caller appends 'unknown' if needed."""
    items = [(int(k), v) for k, v in counter.items() if k.isdigit()]
    items.sort(key=lambda t: t[0])
    return {str(k): v for k, v in items}


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
                if event == "start" and elem.tag == "mame":
                    mame_build = elem.attrib.get("build")
                    mame_mameconfig = elem.attrib.get("mameconfig")

                if event == "start" and elem.tag == "machine":
                    current_machine = elem

                if event == "end" and elem.tag == "machine" and current_machine is elem:
                    mame_name = elem.attrib.get("name")
                    if not mame_name:
                        elem.clear()
                        current_machine = None
                        continue

                    cloneof      = attr_text(elem, "cloneof")
                    isbios       = _yesno_str(attr_yesno_bool(elem, "isbios"))
                    isdevice     = _yesno_str(attr_yesno_bool(elem, "isdevice"))
                    ismechanical = _yesno_str(attr_yesno_bool(elem, "ismechanical"))
                    sampleof     = attr_text(elem, "sampleof")
                    sourcefile   = attr_text(elem, "sourcefile")
                    romof        = attr_text(elem, "romof")  # Not sure if this is still used

                    # CHILD FIELDS
                    description      = element_text(elem, "description", default=None) or None
                    year_raw         = element_text(elem, "year", default="")
                    manufacturer_raw = element_text(elem, "manufacturer", default="")

                    # normalised keys for dists
                    year_key = "unknown"
                    if year_raw and len(year_raw) == 4 and year_raw.isdigit():
                        year_key = year_raw
                    manufacturer_key = manufacturer_raw if manufacturer_raw else "unknown"
                    if manufacturer_key.strip().strip("-.,;:/()[]{}") == "":
                        manufacturer_key = "unknown"

                    # INPUT - Players
                    players_key = "unknown"
                    input_el = elem.find("input")
                    if input_el is not None:
                        players_attr = (input_el.attrib.get("players") or "").strip()
                        #if players_attr.isdigit():
                        #    players_key = players_attr
                        players_val = _int_or_none(input_el.attrib.get("players"))
                        players_key = _bucket_key_int(players_val)   

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
                    sound_channels = None
                    sound_el = elem.find("sound")
                    if sound_el is not None:
                        channels_attr = (sound_el.attrib.get("channels") or "").strip()
                        #if channels_attr.isdigit():
                        #    sound_channels = int(channels_attr)
                        sound_channels = _int_or_none(sound_el.attrib.get("channels"))
                    #sound_channels_per_machine_ctr[str(sound_channels) if sound_channels is not None else "unknown"] += 1
                    sound_channels_per_machine_ctr[_bucket_key_int(sound_channels)] += 1

                    # DEVICE REFS (samples/speaker)
                    device_ref_summary = summarise_device_refs(elem)
                    speakers_per_machine_ctr[str(device_ref_summary["speaker"])] += 1

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
                        remaining = max(0, 10 - len(dropped_displays_examples))
                        if remaining:
                            dropped_displays_examples.extend(_disp_metrics["dropped_examples"][:remaining])

                    # SAMPLES flags
                    sample_children = elem.findall("sample")
                    requires_samples = bool(sampleof or sample_children)
                    if requires_samples:
                        total_requires_samples += 1

                    # ROMS (extracted to utils)
                    rom_count, rom_bytes_total = rom_count_and_bytes(elem)

                    # DISKS (regions only)
                    disk_required, disk_regions, _regions_overall = disk_required_and_regions(elem)
                    # Preserve the original per-disk region counting behaviour
                    for k, v in _regions_overall.items():
                        disk_regions_overall_ctr[k] += v

                    disk_media_platforms_count = len(disk_regions)
                    disk_media_platforms_per_machine_ctr[str(disk_media_platforms_count)] += 1
                    examples = disk_media_examples.setdefault(str(disk_media_platforms_count), [])
                    if len(examples) < 5:
                        examples.append(mame_name)

                    # Totals
                    total_machines += 1
                    if (total_machines % 5000) == 0:
                        log.info(f"[mame_parser::parse_mame_xml] Parsed {total_machines:,} machines so far...")

                    if cloneof:
                        total_clones += 1
                    else:
                        total_parents += 1
                    if isbios == "yes":
                        total_isbios += 1
                    if isdevice == "yes":
                        total_isdevice += 1
                    if ismechanical == "yes":
                        total_ismechanical += 1

                    years_ctr[year_key] += 1
                    manuf_ctr[manufacturer_key] += 1
                    players_ctr[players_key] += 1
                    cpus_per_machine_ctr[str(cpu_count)] += 1
                    sound_devices_per_machine_ctr[str(audio_count)] += 1
                    displays_per_machine_ctr[str(display_count)] += 1

                    # after computing year_raw / manufacturer_raw:
                    year_out         = (year_raw or "")
                    manufacturer_out = (manufacturer_raw or "")

                    # Per-machine record
                    machines_out[mame_name] = {
                        "description": description,
                        "sourcefile": sourcefile,
                        "cloneof": cloneof,
                        "isbios": isbios,
                        "isdevice": isdevice,
                        "ismechanical": ismechanical,
                        "year": year_out,                                                                     
                        "manufacturer": manufacturer_out,                       
                        "rom_count": rom_count,
                        "rom_bytes_total": rom_bytes_total if rom_count else 0,
                        "disk_required": disk_required,
                        "disk_regions": disk_regions,
                        "disk_media_platforms_count": disk_media_platforms_count,
                        "cpu_count": cpu_count,
                        "sound_chip_count": audio_count,
                        "chips": chips_list,
                        "sound_channels": sound_channels,
                        "device_ref": [device_ref_summary],
                        "sampleof": sampleof,
                        "display_count": display_count,
                        "displays": displays_list,
                        "players": None if players_key == "unknown" else int(players_key),
                        "controls": controls_list,
                    }

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
    def _build_summary():
        years_dist = _sorted_numeric_keys_with_unknown_last(dict(years_ctr))
        manuf_dist = _sorted_alpha_with_unknown_last(dict(manuf_ctr))
        display_types_overall_dist = _sorted_alpha_with_unknown_last(dict(display_types_overall_ctr))
        display_tags_overall_dist = _sorted_alpha_with_unknown_last(dict(display_tags_overall_ctr))

        def _numdist(counter):
            dist = _sort_numeric_str(dict(counter))
            if "unknown" in counter:
                dist["unknown"] = counter["unknown"]
            return dist

        players_dist = _numdist(players_ctr)
        cpus_dist = _numdist(cpus_per_machine_ctr)
        sounds_dist = _numdist(sound_devices_per_machine_ctr)
        displays_dist = _numdist(displays_per_machine_ctr)
        speakers_dist = _numdist(speakers_per_machine_ctr)
        sound_channels_dist = _numdist(sound_channels_per_machine_ctr)

        disk_regions_overall_dist = _sorted_alpha_with_unknown_last(dict(disk_regions_overall_ctr))

        years_sum = sum(years_dist.values())
        manufacturers_sum = sum(manuf_dist.values())
        players_sum = sum(players_dist.values())
        cpus_sum = sum(cpus_dist.values())
        sounds_sum = sum(sounds_dist.values())
        displays_sum = sum(displays_dist.values())
        speakers_sum = sum(speakers_dist.values())
        sound_channels_sum = sum(sound_channels_dist.values())
        display_types_overall_sum = sum(display_types_overall_dist.values())
        display_tags_overall_sum = sum(display_tags_overall_dist.values())
        disk_regions_overall_sum = sum(disk_regions_overall_dist.values())

        # versions for header
        mame_build_str = mame_build
        mame_xml_version = (
            mame_build_str.split(" ", 1)[0]
            if isinstance(mame_build_str, str) and mame_build_str.strip()
            else None
        )
        versions_block = {}
        if mame_xml_version:
            versions_block["mame_xml_version"] = mame_xml_version
        if mame_build_str:
            versions_block["mame_build"] = mame_build_str
        if mame_mameconfig is not None:
            versions_block["mameconfig"] = mame_mameconfig


        header = build_summary_header(
            schema_id=SCHEMA_IDS["mame"],
            schema_version=schema_version(SCHEMA_IDS["mame"]),
            versions={
                **versions_block,
                "mame_parser_version": tool_version("mame_parser"),
            },
        )
        
        doc = {
            "header": header,
            "totals": {
                "total_machines": total_machines,
                "total_parents": total_parents,
                "total_clones": total_clones,
                "total_isbios": total_isbios,
                "total_isdevice": total_isdevice,
                "total_ismechanical": total_ismechanical,
                "total_requires_samples": total_requires_samples,
                "years": {
                    "unique": len([k for k in years_dist.keys() if k != "unknown"]),
                    "distribution": years_dist,
                    "sum": years_sum,
                },
                "manufacturers": {
                    "unique": len([k for k in manuf_dist.keys() if k != "unknown"]),
                    "distribution": manuf_dist,
                    "sum": manufacturers_sum,
                },
                "players": {"distribution": players_dist, "sum": players_sum},
                "controls": {
                    "types_overall": {"distribution": _sorted_alpha_with_unknown_last(dict(control_type_overall_ctr)),
                                      "sum": sum(dict(control_type_overall_ctr).values())},
                    "ways_overall": {"distribution": _sorted_alpha_with_unknown_last(dict(control_ways_overall_ctr)),
                                     "sum": sum(dict(control_ways_overall_ctr).values())},
                    "ways2_overall": {"distribution": _sorted_alpha_with_unknown_last(dict(control_ways2_overall_ctr)),
                                      "sum": sum(dict(control_ways2_overall_ctr).values())},
                    "ways3_overall": {"distribution": _sorted_alpha_with_unknown_last(dict(control_ways3_overall_ctr)),
                                      "sum": sum(dict(control_ways3_overall_ctr).values())},
                    "buttons_overall": {"distribution": _numdist(control_buttons_overall_ctr),
                                        "sum": sum(control_buttons_overall_ctr.values())},
                    "reqbuttons_overall": {"distribution": _numdist(control_reqbuttons_overall_ctr),
                                           "sum": sum(control_reqbuttons_overall_ctr.values())},
                },
                "cpus_per_machine": {"distribution": cpus_dist, "sum": cpus_sum},
                "sound_devices_per_machine": {"distribution": sounds_dist, "sum": sounds_sum},
                "displays_per_machine": {"distribution": displays_dist, "sum": displays_sum},
                "display_types_overall": {"distribution": display_types_overall_dist, "sum": display_types_overall_sum},
                "display_tags_overall": {"distribution": display_tags_overall_dist, "sum": display_tags_overall_sum},
                "sound_channels_per_machine": {"distribution": sound_channels_dist, "sum": sound_channels_sum},
                "speakers_per_machine": {"distribution": speakers_dist, "sum": speakers_sum},
                "disk_regions_overall": {"distribution": disk_regions_overall_dist, "sum": disk_regions_overall_sum},
                "disk_media_platforms_per_machine": {
                    "distribution": _sort_numeric_str(dict(disk_media_platforms_per_machine_ctr)) | (
                        {"unknown": disk_media_platforms_per_machine_ctr["unknown"]}
                        if "unknown" in disk_media_platforms_per_machine_ctr else {}
                    ),
                    "sum": sum(disk_media_platforms_per_machine_ctr.values()),
                    "examples": disk_media_examples,
                },
                "invalid_displays_dropped": {
                    "count": dropped_displays_total,
                    "examples": dropped_displays_examples
                },
            },
        }

        # additive aliases + anomalies mirror
        totals = doc["totals"]
        if "total_is_bios" not in totals:
            totals["total_is_bios"] = totals["total_isbios"]
        if "total_is_device" not in totals:
            totals["total_is_device"] = totals["total_isdevice"]
        legacy_drop = totals.get("invalid_displays_dropped")
        if legacy_drop:
            doc.setdefault("anomalies", {}).setdefault("dropped_displays", legacy_drop)
        return doc

    summary = _build_summary()

    # ----------------------------
    # Invariants (warnings only)
    # ----------------------------
    def _sum(counter):
        return sum(counter.values())

    checks_equal_total = [
        ("years_ctr", _sum(years_ctr)),
        ("manuf_ctr", _sum(manuf_ctr)),
        ("players_ctr", _sum(players_ctr)),
        ("cpus_per_machine_ctr", _sum(cpus_per_machine_ctr)),
        ("sound_devices_per_machine_ctr", _sum(sound_devices_per_machine_ctr)),
        ("displays_per_machine_ctr", _sum(displays_per_machine_ctr)),
        ("speakers_per_machine_ctr", _sum(speakers_per_machine_ctr)),
        ("sound_channels_per_machine_ctr", _sum(sound_channels_per_machine_ctr)),
        ("disk_media_platforms_per_machine_ctr", _sum(disk_media_platforms_per_machine_ctr)),
    ]
    for name, val in checks_equal_total:
        if val != total_machines:
            log.warning(f"[mame_parser::parse_mame_xml] Invariant: sum({name})={val} != total_machines={total_machines}")

    expected_total_displays = sum(int(k) * v for k, v in displays_per_machine_ctr.items() if k.isdigit())
    types_sum = _sum(display_types_overall_ctr)
    tags_sum = _sum(display_tags_overall_ctr)
    if types_sum != expected_total_displays:
        log.warning(f"[mame_parser::parse_mame_xml] Display types total {types_sum} != expected {expected_total_displays}")
    if tags_sum != expected_total_displays:
        log.warning(f"[mame_parser::parse_mame_xml] Display tags total {tags_sum} != expected {expected_total_displays}")

    disk_flag_yes_empty = 0
    disk_flag_no_nonempty = 0
    for m in machines_out.values():
        dr = m.get("disk_required")
        regs = m.get("disk_regions") or []
        if dr == "yes" and not regs:
            disk_flag_yes_empty += 1
        elif dr == "no" and regs:
            disk_flag_no_nonempty += 1
    if disk_flag_yes_empty or disk_flag_no_nonempty:
        log.warning(f"[mame_parser::parse_mame_xml] Disk consistency: yes+empty={disk_flag_yes_empty}, no+nonempty={disk_flag_no_nonempty}")

    total_controls_entries = sum(len(m.get("controls") or []) for m in machines_out.values())
    ctrl_sums = [
        ("control_type_overall", _sum(control_type_overall_ctr)),
        ("control_ways_overall", _sum(control_ways_overall_ctr)),
        ("control_ways2_overall", _sum(control_ways2_overall_ctr)),
        ("control_ways3_overall", _sum(control_ways3_overall_ctr)),
        ("control_buttons_overall", _sum(control_buttons_overall_ctr)),
        ("control_reqbuttons_overall", _sum(control_reqbuttons_overall_ctr)),
    ]
    for label, val in ctrl_sums:
        if val != total_controls_entries:
            log.warning(f"[mame_parser::parse_mame_xml] Controls total mismatch: {label}={val} != {total_controls_entries}")

    cpu_mismatch = audio_mismatch = 0
    for m in machines_out.values():
        chips = m.get("chips") or []
        cpus = sum(1 for c in chips if (c.get("type") or "").lower() == "cpu")
        audios = sum(1 for c in chips if (c.get("type") or "").lower() == "audio")
        if cpus != (m.get("cpu_count") or 0):
            cpu_mismatch += 1
        if audios != (m.get("sound_chip_count") or 0):
            audio_mismatch += 1
    if cpu_mismatch or audio_mismatch:
        log.warning(f"[mame_parser::parse_mame_xml] Chip count mismatches: cpu={cpu_mismatch}, audio={audio_mismatch}")

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
