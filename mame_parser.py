"""
Filename: mame_parser.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Parses the full MAME XML and writes:
  - output/mame_machines.json              (canonical, unfiltered dump)
  - data/mame_parsing_summary.json         (totals-only summary)

No classification or filtering is applied here. Downstream modules will handle
selection (using .ini metadata) and the join with Gaming-History.

This file is part of a student project and is not intended for commercial use.
"""

from __future__ import annotations

from pathlib import Path
import json
import time
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Dict, Any
import logging

from config import LOG_LEVEL
from logger import setup_logger, debug_log

log = setup_logger(log_level=LOG_LEVEL)

def _sorted_numeric_keys_with_unknown_last(counter: Dict[str, int]) -> Dict[str, int]:
    """Return a dict sorted by numeric key ascending, with 'unknown' last if present."""
    numeric = []
    unknown = None
    other = 0
    for k, v in counter.items():
        if k == "unknown":
            unknown = v
        else:
            if k.isdigit():
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
    """Case-insensitive A–Z, with 'unknown' last if present."""
    items = [(k, v) for k, v in counter.items() if k != "unknown"]
    items.sort(key=lambda kv: kv[0].lower())
    out = {k: v for k, v in items}
    if "unknown" in counter:
        out["unknown"] = counter["unknown"]
    return out


def parse_mame_xml(file_path: Path, encodings: dict[str, str], max_records: int = 0) -> bool:
    """
    Parse the entire mame.xml and write:
      - output/mame_machines.json
      - data/mame_parsing_summary.json

    Returns:
        list[dict]: Unfiltered list of machine dicts (canonical fields).
    """
    start = time.perf_counter()
    log.info(f"Starting full MAME XML parsing: {file_path.name}" +
             (f" (max {max_records} records)" if max_records else " (no limit)"))

    # Work out dirs relative to the given data file
    data_dir = file_path.parent
    output_dir = data_dir.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    mame_encoding = encodings["mame.xml"]

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
    control_type_overall_ctr  = Counter()
    control_ways_overall_ctr  = Counter()
    control_ways2_overall_ctr = Counter()
    control_ways3_overall_ctr = Counter()
    control_buttons_overall_ctr     = Counter()  # histogram of buttons per control
    control_reqbuttons_overall_ctr  = Counter()  # histogram of reqbuttons per control    
    cpus_per_machine_ctr = Counter()
    sound_devices_per_machine_ctr = Counter()
    displays_per_machine_ctr = Counter()
    speakers_per_machine_ctr = Counter()        # counts <device_ref name="speaker">
    sound_channels_per_machine_ctr = Counter()  # from <sound channels="">
    display_types_overall_ctr = Counter()  # raster/vector/lcd/svg/unknown
    display_tags_overall_ctr = Counter()   # e.g. screen, screen0, left, right, (unspecified)
    disk_regions_overall_ctr = Counter()  # e.g. {"cdrom": 90, "laserdisc": 12, "harddisk": 15, "unknown": 3}

    machines_out: Dict[str, Dict[str, Any]] = {}

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

                    cloneof = elem.attrib.get("cloneof")
                    isbios = elem.attrib.get("isbios", "no")
                    isdevice = elem.attrib.get("isdevice", "no")
                    ismechanical = elem.attrib.get("ismechanical", "no")
                    #runnable = elem.attrib.get("runnable", "yes")
                    sampleof = elem.attrib.get("sampleof")
                    sourcefile = elem.attrib.get("sourcefile")
                    romof = elem.attrib.get("romof")

                    # Core child fields
                    desc_el = elem.find("description")
                    description = (desc_el.text or "").strip() if desc_el is not None else ""

                    year_el = elem.find("year")
                    year_raw = (year_el.text or "").strip() if year_el is not None else ""

                    manuf_el = elem.find("manufacturer")
                    manufacturer_raw = (manuf_el.text or "").strip() if manuf_el is not None else ""

                    # Normalise for distributions
                    year_key = "unknown"
                    if year_raw and len(year_raw) == 4 and year_raw.isdigit():
                        year_key = year_raw

                    manufacturer_key = manufacturer_raw if manufacturer_raw else "unknown"
                    if manufacturer_key.strip().strip("-.,;:/()[]{}") == "":
                        manufacturer_key = "unknown"

                    # INPUT – players
                    players_key = "unknown"
                    input_el = elem.find("input")
                    if input_el is not None:
                        players_attr = (input_el.attrib.get("players") or "").strip()
                        if players_attr.isdigit():
                            players_key = players_attr
                                                        
                    # INPUT – controls (per-player/per-device)
                    controls_list = []
                    if input_el is not None:
                        for ctrl in input_el.findall("control"):
                            c_type = (ctrl.attrib.get("type") or "").strip().lower() or None

                            player_attr = (ctrl.attrib.get("player") or "").strip()
                            c_player = int(player_attr) if player_attr.isdigit() else None

                            buttons_attr = (ctrl.attrib.get("buttons") or "").strip()
                            c_buttons = int(buttons_attr) if buttons_attr.isdigit() else None

                            reqbuttons_attr = (ctrl.attrib.get("reqbuttons") or "").strip()
                            c_reqbuttons = int(reqbuttons_attr) if reqbuttons_attr.isdigit() else None

                            c_ways  = (ctrl.attrib.get("ways")  or "").strip() or None
                            c_ways2 = (ctrl.attrib.get("ways2") or "").strip() or None
                            c_ways3 = (ctrl.attrib.get("ways3") or "").strip() or None

                            # Per-control output (player first for readability)
                            controls_list.append({
                                "player": c_player,
                                "type": c_type,
                                "buttons": c_buttons,
                                "reqbuttons": c_reqbuttons,
                                "ways": c_ways,
                                "ways2": c_ways2,
                                "ways3": c_ways3,
                            })

                            # ---- Summary counters (overall, across all controls) ----
                            control_type_overall_ctr[(c_type or "unknown")] += 1
                            control_ways_overall_ctr[(c_ways or "unknown").lower()]   += 1
                            control_ways2_overall_ctr[(c_ways2 or "unknown").lower()] += 1
                            control_ways3_overall_ctr[(c_ways3 or "unknown").lower()] += 1
                            control_buttons_overall_ctr[str(c_buttons) if c_buttons is not None else "unknown"] += 1
                            control_reqbuttons_overall_ctr[str(c_reqbuttons) if c_reqbuttons is not None else "unknown"] += 1
                            

                    # SOUND – channels  (correctly record audio mixer channels, not speakers)
                    sound_channels = None
                    sound_el = elem.find("sound")
                    if sound_el is not None:
                        channels_attr = (sound_el.attrib.get("channels") or "").strip()
                        if channels_attr.isdigit():
                            sound_channels = int(channels_attr)

                    # update channels distribution
                    sound_channels_per_machine_ctr[
                        str(sound_channels) if sound_channels is not None else "unknown"
                    ] += 1

                    # DEVICE_REF summary: samples present? how many speakers?
                    has_samples_device_ref = False
                    speaker_ref_count = 0
                    for dref in elem.findall("device_ref"):
                        name = (dref.attrib.get("name") or "").strip().lower()
                        if name == "samples":
                            has_samples_device_ref = True
                        elif name == "speaker":
                            speaker_ref_count += 1

                    device_ref_summary = {
                        "samples": "yes" if has_samples_device_ref else "no",
                        "speaker": speaker_ref_count,
                    }

                    # speakers distribution now reflects physical speakers counted via device_ref
                    speakers_per_machine_ctr[str(speaker_ref_count)] += 1


                    # CHIPS
                    cpu_count = 0
                    audio_count = 0
                    chips_list = []   # NEW: collect per-chip details
                    for chip in elem.findall("chip"):
                        ctype = (chip.attrib.get("type") or "").strip().lower()
                        chip_name  = (chip.attrib.get("name") or "").strip()
                        tag   = chip.attrib.get("tag")  # may be None
                        clock_attr = (chip.attrib.get("clock") or "").strip()
                        clock_hz = int(clock_attr) if clock_attr.isdigit() else None

                        if ctype == "cpu":
                            cpu_count += 1
                        elif ctype == "audio":
                            audio_count += 1

                        chips_list.append({
                            "type": ctype,
                            "name": chip_name,
                            "tag": tag,
                            "clock_hz": clock_hz,
                        })



                    # DISPLAYS (collect raw details, and update overall tag/type counters)
                    #display_count = len(elem.findall("display"))
                    displays_list = []
                    for d in elem.findall("display"):
                        d_type = (d.attrib.get("type") or "").strip().lower() or None
                        d_tag  = (d.attrib.get("tag") or "").strip() or None

                        rot_attr = (d.attrib.get("rotate") or "").strip()
                        d_rotate = int(rot_attr) if rot_attr.isdigit() else None

                        w_attr = (d.attrib.get("width") or "").strip()
                        h_attr = (d.attrib.get("height") or "").strip()
                        d_width  = int(w_attr) if w_attr.isdigit() else None
                        d_height = int(h_attr) if h_attr.isdigit() else None

                        r_attr = (d.attrib.get("refresh") or "").strip()
                        try:
                            d_refresh_hz = float(r_attr) if r_attr else None
                        except ValueError:
                            d_refresh_hz = None

                        displays_list.append({
                            "tag": d_tag,
                            "type": d_type,
                            "rotate": d_rotate,
                            "width": d_width,
                            "height": d_height,
                            "refresh_hz": d_refresh_hz,
                        })

                        # Overall counters (types/tags)
                        if d_type:
                            #display_types_overall_ctr[d_type] += 1
                            display_types_overall_ctr[d_type or "unknown"] += 1
                        else:
                            #display_types_overall_ctr["unknown"] += 1
                            display_types_overall_ctr[d_type or "unknown"] += 1

                        #display_tags_overall_ctr[d_tag or "unspecified"] += 1
                        display_tags_overall_ctr[d_tag or "unknown"] += 1


                    display_count = len(displays_list)


                    # SAMPLES requirement
                    sample_children = elem.findall("sample")
                    requires_samples = bool(sampleof or sample_children)
                    if requires_samples:
                        total_requires_samples += 1

                    # Totals and distributions
                    total_machines += 1
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

                    # ROMS — count and total size
                    rom_elems = elem.findall("rom")
                    rom_count = len(rom_elems)
                    rom_bytes_total = 0
                    for r in rom_elems:
                        sz = (r.attrib.get("size") or "").strip()
                        if sz.isdigit():
                            rom_bytes_total += int(sz)

                    # DISK (region only) — detect presence and summarise region types
                    disk_elems = elem.findall("disk")
                    disk_required = "yes" if disk_elems else "no"

                    disk_regions_set = set()
                    for d in disk_elems:
                        region_raw = (d.attrib.get("region") or "").strip()
                        region_key = region_raw.lower() if region_raw else "unknown"
                        disk_regions_set.add(region_key)
                        disk_regions_overall_ctr[region_key] += 1

                    # Unique, sorted list of regions per machine (e.g. ["cdrom"], ["laserdisc","ldsound"])
                    disk_regions = sorted(disk_regions_set)


                    machines_out[mame_name] = {
                        "description": description,
                        "sourcefile": sourcefile,
                        "cloneof": cloneof,
                        "romof": romof,
                        "isbios": isbios,
                        "isdevice": isdevice,
                        "ismechanical": ismechanical,
                        #"runnable": runnable,
                        "sampleof": sampleof,
                        "year": year_raw,
                        "manufacturer": manufacturer_raw,
                        "rom_count": rom_count,
                        "rom_bytes_total": rom_bytes_total if rom_count else 0,                        
                        "disk_required": disk_required,  # "yes" | "no"
                        "disk_regions": disk_regions,    # unique, sorted list (may be [])
                        "players": None if players_key == "unknown" else int(players_key),
                        "controls": controls_list,
                        "cpu_count": cpu_count,
                        "sound_chip_count": audio_count,
                        "chips": chips_list,
                        "display_count": display_count,
                        "displays": displays_list,
                        "sound_channels": sound_channels,  # from <sound channels="">
                        "device_ref": [device_ref_summary],
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

    # Prepare ordered distributions
    years_dist = _sorted_numeric_keys_with_unknown_last(dict(years_ctr))
    manuf_dist = _sorted_alpha_with_unknown_last(dict(manuf_ctr))
    #display_types_overall_dist = _sorted_alpha_with_unknown_last(dict(display_types_overall_ctr), "unknown")
    #display_tags_overall_dist  = _sorted_alpha_with_unknown_last(dict(display_tags_overall_ctr), "unspecified")
    display_types_overall_dist = _sorted_alpha_with_unknown_last(dict(display_types_overall_ctr))
    display_tags_overall_dist  = _sorted_alpha_with_unknown_last(dict(display_tags_overall_ctr))


    def _sort_numeric_str(counter: Dict[str, int]) -> Dict[str, int]:
        items = [(int(k), v) for k, v in counter.items() if k.isdigit()]
        items.sort(key=lambda t: t[0])
        return {str(k): v for k, v in items}


    players_dist = _sort_numeric_str(dict(players_ctr))
    if "unknown" in players_ctr:
        players_dist["unknown"] = players_ctr["unknown"]

    cpus_dist = _sort_numeric_str(dict(cpus_per_machine_ctr))
    sounds_dist = _sort_numeric_str(dict(sound_devices_per_machine_ctr))
    displays_dist = _sort_numeric_str(dict(displays_per_machine_ctr))
    #speakers_dist = _sort_numeric_str(dict(speakers_per_machine_ctr))
    sound_channels_dist = _sort_numeric_str(dict(sound_channels_per_machine_ctr))
    if "unknown" in sound_channels_per_machine_ctr:
        sound_channels_dist["unknown"] = sound_channels_per_machine_ctr["unknown"]
    #
    speakers_dist     = _sort_numeric_str(dict(speakers_per_machine_ctr))
    years_sum         = sum(years_dist.values())
    manufacturers_sum = sum(manuf_dist.values())
    players_sum       = sum(players_dist.values())
    # Controls distributions
    control_type_overall_dist  = _sorted_alpha_with_unknown_last(dict(control_type_overall_ctr))
    control_ways_overall_dist  = _sorted_alpha_with_unknown_last(dict(control_ways_overall_ctr))
    control_ways2_overall_dist = _sorted_alpha_with_unknown_last(dict(control_ways2_overall_ctr))
    control_ways3_overall_dist = _sorted_alpha_with_unknown_last(dict(control_ways3_overall_ctr))

    control_buttons_overall_dist = _sort_numeric_str(dict(control_buttons_overall_ctr))
    if "unknown" in control_buttons_overall_ctr:
        control_buttons_overall_dist["unknown"] = control_buttons_overall_ctr["unknown"]

    control_reqbuttons_overall_dist = _sort_numeric_str(dict(control_reqbuttons_overall_ctr))
    if "unknown" in control_reqbuttons_overall_ctr:
        control_reqbuttons_overall_dist["unknown"] = control_reqbuttons_overall_ctr["unknown"]

    # Sums for quick sanity checks
    control_type_overall_sum  = sum(control_type_overall_dist.values())
    control_ways_overall_sum  = sum(control_ways_overall_dist.values())
    control_ways2_overall_sum = sum(control_ways2_overall_dist.values())
    control_ways3_overall_sum = sum(control_ways3_overall_dist.values())
    control_buttons_overall_sum    = sum(control_buttons_overall_dist.values())
    control_reqbuttons_overall_sum = sum(control_reqbuttons_overall_dist.values())
    #    
    cpus_sum          = sum(cpus_dist.values())
    sounds_sum        = sum(sounds_dist.values())
    sound_channels_sum = sum(sound_channels_dist.values())
    displays_sum      = sum(displays_dist.values())
    display_types_overall_sum = sum(display_types_overall_dist.values())
    display_tags_overall_sum  = sum(display_tags_overall_dist.values())
    sound_channels_sum = sum(sound_channels_dist.values())
    speakers_sum       = sum(speakers_dist.values())
    disk_regions_overall_dist = _sorted_alpha_with_unknown_last(dict(disk_regions_overall_ctr))
    disk_regions_overall_sum  = sum(disk_regions_overall_dist.values())
 

    # Build totals summary
    summary = {
        "mame": {
            "build": mame_build,
            "mameconfig": mame_mameconfig,
        },
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
            "players": {
                "distribution": players_dist,
                "sum": players_sum,
            },
            "controls": {
                "types_overall": {
                    "distribution": control_type_overall_dist,
                    "sum": control_type_overall_sum
                },
                "ways_overall": {
                    "distribution": control_ways_overall_dist,
                    "sum": control_ways_overall_sum
                },
                "ways2_overall": {
                    "distribution": control_ways2_overall_dist,
                    "sum": control_ways2_overall_sum
                },
                "ways3_overall": {
                    "distribution": control_ways3_overall_dist,
                    "sum": control_ways3_overall_sum
                },
                "buttons_overall": {
                    "distribution": control_buttons_overall_dist,
                    "sum": control_buttons_overall_sum
                },
                "reqbuttons_overall": {
                    "distribution": control_reqbuttons_overall_dist,
                    "sum": control_reqbuttons_overall_sum
                }
            },            
            "cpus_per_machine": {
                "distribution": cpus_dist,
                "sum": cpus_sum,
            },
            "sound_devices_per_machine": {
                "distribution": sounds_dist,
                "sum": sounds_sum,
            },
            "displays_per_machine": {
                "distribution": displays_dist,
                "sum": displays_sum,
            },
            "display_types_overall": {
                "distribution": display_types_overall_dist,
                "sum": display_types_overall_sum
            },
            "display_tags_overall": {
                "distribution": display_tags_overall_dist,
                "sum": display_tags_overall_sum
            },
            "sound_channels_per_machine": {
                "distribution": sound_channels_dist,
                "sum": sound_channels_sum,
            },            
            "speakers_per_machine": {
                "distribution": speakers_dist,
                "sum": speakers_sum,
            },            
            "disk_regions_overall": {
                "distribution": disk_regions_overall_dist,
                "sum": disk_regions_overall_sum
            },
        }
    }

    # Deterministic order for machines output
    machines_sorted = {k: machines_out[k] for k in sorted(machines_out.keys())}

    # Write files
    machines_path = (data_dir.parent / "output" / "mame_machines.json")
    summary_path = (data_dir / "mame_parsing_summary.json")

    with open(machines_path, "w", encoding="utf-8") as f:
        json.dump(machines_sorted, f, ensure_ascii=False, indent=2)

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    log.info(f"Wrote canonical machines: {machines_path}")
    log.info(f"Wrote MAME totals summary: {summary_path}")
    log.info(f"MAME XML parsing completed in {parse_seconds:.2f} seconds")

    # Return a list (keeps main.py happy)
    #result_list = [machines_sorted[k] for k in machines_sorted.keys()]
    #debug_log(f"First 5 machines (canonical): {[m['name'] for m in result_list[:5]]}")
    #return result_list
    return True
