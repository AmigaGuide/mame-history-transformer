"""
Filename: mame_parser.py
Version: 1.0.0
Last modified: 2025-09-10
Author: Jason (XtC) Skelly (Open University TM470, 2025)

Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Purpose:
Parse the full MAME XML and write:
  - output/mame_machines.json              (canonical, unfiltered dump)
  - data/mame_parsing_summary.json         (totals-only summary)
  - output/mame_parent_index.json          (parent -> clones index + reverse map)

No classification or filtering is applied here. Downstream modules will handle
selection (using .ini metadata) and the join with Gaming-History.

Licence:
This file forms part of a student project and is not intended for commercial use.
See repository LICENCE for details.
"""

from __future__ import annotations

import datetime
import json
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Dict

#from config import LOG_LEVEL
from mht.utils.config import LOG_LEVEL

#from logger import setup_logger
from mht.utils.logger import setup_logger

log = setup_logger(log_level=LOG_LEVEL)

__all__ = ["MAME_PARSER_SCHEMA", "parse_mame_xml"]

MAME_PARSER_SCHEMA = "1.0"


def _build_parent_index(machines: dict[str, dict]) -> dict:
    """
    Build a minimal parent/clone index from the parsed MAME machines.

    Output shape:
    {
      "parents": { parent: [sorted, unique clones], ... },
      "child_to_parent": { clone: parent, ... }
    }

    Only parents that actually have >= 1 clone are included.
    """
    parents: dict[str, list[str]] = {}
    child_to_parent: dict[str, str] = {}

    for mname, info in machines.items():
        parent = info.get("cloneof")
        if not parent:
            continue
        # Record reverse map
        child_to_parent[mname] = parent
        # Record forward map
        lst = parents.setdefault(parent, [])
        lst.append(mname)

    # Deduplicate + sort clone lists; sort parent keys for stable diffs
    parents_sorted: dict[str, list[str]] = {
        p: sorted(set(clones)) for p, clones in parents.items() if clones
    }
    parents_sorted = {p: parents_sorted[p] for p in sorted(parents_sorted.keys())}

    # Sort reverse map by clone name for deterministic output
    child_to_parent_sorted = {c: child_to_parent[c] for c in sorted(child_to_parent.keys())}

    return {"parents": parents_sorted, "child_to_parent": child_to_parent_sorted}


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

    Args:
        file_path: Path to data/mame.xml.
        encodings: Mapping of filename -> encoding (expects 'mame.xml' key).
        max_records: Optional cap for debugging; 0 means no limit.

    Returns:
        bool: True on success, False if XML parse error occurs.

    Notes:
        - Uses ElementTree.iterparse to keep memory bounded.
        - Emits progress every 5,000 machines.
        - Keeps distributions and invariants for quick sanity checks in the summary.
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
    control_buttons_overall_ctr     = Counter()
    control_reqbuttons_overall_ctr  = Counter()
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

                # --- MACHINE: START/END HANDLING ------------------------------------------------
                if event == "end" and elem.tag == "machine" and current_machine is elem:
                    mame_name = elem.attrib.get("name")
                    if not mame_name:
                        elem.clear()
                        current_machine = None
                        continue

                    # --- CORE ATTRIBUTES (name/cloneof/isbios/isdevice/ismechanical/sourcefile/...) ---
                    cloneof = elem.attrib.get("cloneof")
                    isbios = elem.attrib.get("isbios", "no")
                    isdevice = elem.attrib.get("isdevice", "no")
                    ismechanical = elem.attrib.get("ismechanical", "no")
                    sampleof = elem.attrib.get("sampleof")
                    sourcefile = elem.attrib.get("sourcefile")
                    romof = elem.attrib.get("romof")

                    # --- CHILD FIELDS: description/year/manufacturer ---------------------------------
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

                    # --- INPUT: players + controls ---------------------------------------------------
                    players_key = "unknown"
                    input_el = elem.find("input")
                    if input_el is not None:
                        players_attr = (input_el.attrib.get("players") or "").strip()
                        if players_attr.isdigit():
                            players_key = players_attr
                                                        
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
                            

                    # --- SOUND: channels + device_ref(speaker/samples) -------------------------------
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

                    speakers_per_machine_ctr[str(speaker_ref_count)] += 1


                    # --- CHIPS -----------------------------------------------------------------------
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


                    # --- DISPLAYS --------------------------------------------------------------------
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

                        # --- VALIDATION: keep only sensible displays ---
                        # Vector: allow unknown dimensions. Others must have positive width & height.
                        valid = True
                        if (d_type != "vector"):
                            if (d_width is None or d_height is None or
                                not isinstance(d_width, int) or not isinstance(d_height, int) or
                                d_width <= 0 or d_height <= 0):
                                valid = False

                        if not valid:
                            log.warning(f"[mame_parser::parse_mame_xml] Dropping invalid display on {mame_name}: "
                                        f"type={d_type}, width={d_width}, height={d_height}, tag={d_tag}")
                            # NEW: track count + a few examples
                            dropped_displays_total += 1
                            if len(dropped_displays_examples) < 10:
                                dropped_displays_examples.append({
                                    "machine": mame_name,
                                    "type": d_type,
                                    "width": d_width,
                                    "height": d_height,
                                    "tag": d_tag,
                                })
                            continue

                        displays_list.append({
                            "tag": d_tag,
                            "type": d_type,
                            "rotate": d_rotate,
                            "width": d_width,
                            "height": d_height,
                            "refresh_hz": d_refresh_hz,
                        })
                       
                        # Overall counters (types/tags)
                        display_types_overall_ctr[d_type or "unknown"] += 1
                        display_tags_overall_ctr[d_tag or "unknown"] += 1

                    display_count = len(displays_list)

                    # --- SAMPLES: presence-only (sampleof or <sample>) --------------------------------
                    sample_children = elem.findall("sample")
                    requires_samples = bool(sampleof or sample_children)
                    if requires_samples:
                        total_requires_samples += 1

                    # --- ROMS ------------------------------------------------------------------------
                    rom_elems = elem.findall("rom")
                    rom_count = len(rom_elems)
                    rom_bytes_total = 0
                    for r in rom_elems:
                        sz = (r.attrib.get("size") or "").strip()
                        if sz.isdigit():
                            rom_bytes_total += int(sz)

                    # --- DISK: regions only ----------------------------------------------------------
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
                    disk_media_platforms_count = len(disk_regions)  # 0 for ROM-only machines
                    disk_media_platforms_per_machine_ctr[str(disk_media_platforms_count)] += 1

                    # Keep a few illustrative examples per bucket (0..N) for the summary
                    disk_media_examples = locals().setdefault("disk_media_examples", {})  # create once in function scope
                    examples = disk_media_examples.setdefault(str(disk_media_platforms_count), [])
                    if len(examples) < 5:
                        examples.append(mame_name)


                    # Totals and distributions
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

                    # --- PER-MACHINE RECORD ----------------------------------------------------------
                    machines_out[mame_name] = {
                        # Identity & lineage
                        "description": description,
                        "sourcefile": sourcefile,
                        "cloneof": cloneof,
                        "isbios": isbios,
                        "isdevice": isdevice,
                        "ismechanical": ismechanical,

                        # Publication
                        "year": year_raw,
                        "manufacturer": manufacturer_raw,

                        # Storage / media
                        "rom_count": rom_count,
                        "rom_bytes_total": rom_bytes_total if rom_count else 0,
                        "disk_required": disk_required,         # "yes" | "no"
                        "disk_regions": disk_regions,           # list (can be [])
                        "disk_media_platforms_count": disk_media_platforms_count,

                        # Chips
                        "cpu_count": cpu_count,
                        "sound_chip_count": audio_count,
                        "chips": chips_list,                    # list of {type,name,tag,clock_hz}

                        # Audio
                        "sound_channels": sound_channels,       # int or None
                        "device_ref": [device_ref_summary],     # [{"samples":"yes|no","speaker": N}]
                        "sampleof": sampleof,                   # string or None

                        # Video / display
                        "display_count": display_count,
                        "displays": displays_list,               # list of {tag,type,rotate,width,height,refresh_hz}
                        
                        # Input / controls
                        "players": None if players_key == "unknown" else int(players_key),
                        "controls": controls_list,              # list of {player,type,buttons,reqbuttons,ways,ways2,ways3}
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
    generated_at_utc = datetime.datetime.utcnow().isoformat() + "Z"


    def _build_summary():
        """Build the totals/metrics summary block for the parsed MAME dataset."""
        # Core distributions
        years_dist  = _sorted_numeric_keys_with_unknown_last(dict(years_ctr))
        manuf_dist  = _sorted_alpha_with_unknown_last(dict(manuf_ctr))
        display_types_overall_dist = _sorted_alpha_with_unknown_last(dict(display_types_overall_ctr))
        display_tags_overall_dist  = _sorted_alpha_with_unknown_last(dict(display_tags_overall_ctr))

        def _numdist(counter):
            """Normalise numeric-string keyed histograms (append 'unknown' last if present)."""
            dist = _sort_numeric_str(dict(counter))
            if "unknown" in counter:
                dist["unknown"] = counter["unknown"]
            return dist

        players_dist         = _numdist(players_ctr)
        cpus_dist            = _numdist(cpus_per_machine_ctr)
        sounds_dist          = _numdist(sound_devices_per_machine_ctr)
        displays_dist        = _numdist(displays_per_machine_ctr)
        speakers_dist        = _numdist(speakers_per_machine_ctr)
        sound_channels_dist  = _numdist(sound_channels_per_machine_ctr)

        # Disks (regions only)
        disk_regions_overall_dist = _sorted_alpha_with_unknown_last(dict(disk_regions_overall_ctr))
        disk_media_platforms_dist = _numdist(disk_media_platforms_per_machine_ctr)
        disk_media_platforms_sum  = sum(disk_media_platforms_dist.values())

        # Controls
        control_type_overall_dist  = _sorted_alpha_with_unknown_last(dict(control_type_overall_ctr))
        control_ways_overall_dist  = _sorted_alpha_with_unknown_last(dict(control_ways_overall_ctr))
        control_ways2_overall_dist = _sorted_alpha_with_unknown_last(dict(control_ways2_overall_ctr))
        control_ways3_overall_dist = _sorted_alpha_with_unknown_last(dict(control_ways3_overall_ctr))
        control_buttons_overall_dist    = _numdist(control_buttons_overall_ctr)
        control_reqbuttons_overall_dist = _numdist(control_reqbuttons_overall_ctr)

        # Convenience sums (sanity checks)
        years_sum                   = sum(years_dist.values())
        manufacturers_sum           = sum(manuf_dist.values())
        players_sum                 = sum(players_dist.values())
        cpus_sum                    = sum(cpus_dist.values())
        sounds_sum                  = sum(sounds_dist.values())
        displays_sum                = sum(displays_dist.values())
        speakers_sum                = sum(speakers_dist.values())
        sound_channels_sum          = sum(sound_channels_dist.values())
        display_types_overall_sum   = sum(display_types_overall_dist.values())
        display_tags_overall_sum    = sum(display_tags_overall_dist.values())
        disk_regions_overall_sum    = sum(disk_regions_overall_dist.values())
        control_type_overall_sum    = sum(control_type_overall_dist.values())
        control_ways_overall_sum    = sum(control_ways_overall_dist.values())
        control_ways2_overall_sum   = sum(control_ways2_overall_dist.values())
        control_ways3_overall_sum   = sum(control_ways3_overall_dist.values())
        control_buttons_overall_sum = sum(control_buttons_overall_dist.values())
        control_reqbuttons_overall_sum = sum(control_reqbuttons_overall_dist.values())

        # --- derive versions for header ---
        mame_build_str = mame_build  # already set above
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

        # --- build doc with HEADER FIRST ---
        doc = {
            "header": {
                "schema_id": "mht.mame.summary",
                "schema_version": "1.0.1",
                "generated_at": generated_at_utc,
                "versions": versions_block,
            },
            "mame": {
                "mame_parser_schema": MAME_PARSER_SCHEMA,
                "generated_at": generated_at_utc,
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
                "players": {"distribution": players_dist, "sum": players_sum},
                "controls": {
                    "types_overall": {"distribution": control_type_overall_dist, "sum": control_type_overall_sum},
                    "ways_overall":  {"distribution": control_ways_overall_dist,  "sum": control_ways_overall_sum},
                    "ways2_overall": {"distribution": control_ways2_overall_dist, "sum": control_ways2_overall_sum},
                    "ways3_overall": {"distribution": control_ways3_overall_dist, "sum": control_ways3_overall_sum},
                    "buttons_overall":    {"distribution": control_buttons_overall_dist,    "sum": control_buttons_overall_sum},
                    "reqbuttons_overall": {"distribution": control_reqbuttons_overall_dist, "sum": control_reqbuttons_overall_sum},
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
                    "distribution": _numdist(disk_media_platforms_per_machine_ctr),
                    "sum": sum(disk_media_platforms_per_machine_ctr.values()),
                    "examples": disk_media_examples
                },
                "invalid_displays_dropped": {
                    "count": dropped_displays_total,
                    "examples": dropped_displays_examples
                },
            },
        }

        # --- additive aliases + anomalies mirror ---
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


    # --- INVARIANTS & CONSISTENCY CHECKS (warnings only) -------------------------
    def _sum(counter):
        """
        Lightweight helper to sum the values in a count mapping.

        Args:
            counter (Mapping[Any, int]): Histogram or dict of counts.

        Returns:
            int: Sum of all count values.
        """
        return sum(counter.values())

    # Per-machine counters should sum to total machines
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
            log.warning(f"[mame_parser::parse_mame_xml] Invariant: sum({name})={val} "
                        f"!= total_machines={total_machines}")

    # Display totals: overall type/tag counters should equal total number of display entries
    expected_total_displays = sum(int(k) * v for k, v in displays_per_machine_ctr.items() if k.isdigit())
    types_sum = _sum(display_types_overall_ctr)
    tags_sum  = _sum(display_tags_overall_ctr)
    if types_sum != expected_total_displays:
        log.warning(f"[mame_parser::parse_mame_xml] Display types total {types_sum} "
                    f"!= expected_total_displays {expected_total_displays}")
    if tags_sum != expected_total_displays:
        log.warning(f"[mame_parser::parse_mame_xml] Display tags total {tags_sum} "
                    f"!= expected_total_displays {expected_total_displays}")

    # Disk consistency: disk_required vs disk_regions emptiness
    disk_flag_yes_empty = 0
    disk_flag_no_nonempty = 0
    for name, m in machines_out.items():
        dr = m.get("disk_required")
        regs = m.get("disk_regions") or []
        if dr == "yes" and not regs:
            disk_flag_yes_empty += 1
        elif dr == "no" and regs:
            disk_flag_no_nonempty += 1
    if disk_flag_yes_empty or disk_flag_no_nonempty:
        log.warning(f"[mame_parser::parse_mame_xml] Disk consistency: "
                    f"yes+empty={disk_flag_yes_empty}, no+nonempty={disk_flag_no_nonempty}")

    # Controls consistency: all control-related histograms should agree on entry count
    total_controls_entries = sum(len(m.get("controls") or []) for m in machines_out.values())
    ctrl_type_sum   = _sum(control_type_overall_ctr)
    ctrl_ways_sum   = _sum(control_ways_overall_ctr)
    ctrl_ways2_sum  = _sum(control_ways2_overall_ctr)
    ctrl_ways3_sum  = _sum(control_ways3_overall_ctr)
    ctrl_btns_sum   = _sum(control_buttons_overall_ctr)
    ctrl_req_sum    = _sum(control_reqbuttons_overall_ctr)
    for label, val in [
        ("control_type_overall", ctrl_type_sum),
        ("control_ways_overall", ctrl_ways_sum),
        ("control_ways2_overall", ctrl_ways2_sum),
        ("control_ways3_overall", ctrl_ways3_sum),
        ("control_buttons_overall", ctrl_btns_sum),
        ("control_reqbuttons_overall", ctrl_req_sum),
    ]:
        if val != total_controls_entries:
            log.warning(f"[mame_parser::parse_mame_xml] Controls total mismatch: {label}={val} "
                        f"!= total_controls_entries={total_controls_entries}")

    # Chip counts per machine: cpu_count vs chips list, audio_count vs chips list
    cpu_mismatch = audio_mismatch = 0
    for name, m in machines_out.items():
        chips = m.get("chips") or []
        cpus   = sum(1 for c in chips if (c.get("type") or "").lower() == "cpu")
        audios = sum(1 for c in chips if (c.get("type") or "").lower() == "audio")
        if cpus != (m.get("cpu_count") or 0):
            cpu_mismatch += 1
        if audios != (m.get("sound_chip_count") or 0):
            audio_mismatch += 1
    if cpu_mismatch or audio_mismatch:
        log.warning(f"[mame_parser::parse_mame_xml] Chip count mismatches: "
                    f"cpu={cpu_mismatch}, audio={audio_mismatch}")


    # Deterministic order for machines output
    machines_sorted = {k: machines_out[k] for k in sorted(machines_out.keys())}

    # Write files
    machines_path = (data_dir.parent / "output" / "mame_machines.json")
    summary_path = (data_dir / "mame_parsing_summary.json")

    with open(machines_path, "w", encoding="utf-8") as f:
        json.dump(machines_sorted, f, ensure_ascii=False, indent=2)
    log.info(f"Wrote canonical machines: {machines_path}")

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    log.info(f"Wrote MAME totals summary: {summary_path}")


    # ----------------------------
    # Also write parent/clone index
    # ----------------------------
    parent_index = _build_parent_index(machines_out) # machines_out vs machines_sorted: content identical
    parent_index_path = (data_dir.parent / "output" / "mame_parent_index.json")
    parent_index_path.parent.mkdir(parents=True, exist_ok=True)

    with open(parent_index_path, "w", encoding="utf-8") as f:
        json.dump(parent_index, f, ensure_ascii=False, indent=2)

    log.info(f"Wrote {parent_index_path} "
             f"({len(parent_index['parents'])} parents-with-clones, "
             f"{len(parent_index['child_to_parent'])} clones)")

    log.info(f"MAME XML parsing completed in {parse_seconds:.2f} seconds")
    
    log.info(f"Invalid display rows dropped: {dropped_displays_total}")

    return True
