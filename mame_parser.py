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


def parse_mame_xml(file_path: Path, encodings: dict[str, str], max_records: int = 0) -> list[dict]:
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
    cpus_per_machine_ctr = Counter()
    sound_devices_per_machine_ctr = Counter()
    displays_per_machine_ctr = Counter()
    speakers_per_machine_ctr = Counter()

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
                    name = elem.attrib.get("name")
                    if not name:
                        elem.clear()
                        current_machine = None
                        continue

                    cloneof = elem.attrib.get("cloneof")
                    isbios = elem.attrib.get("isbios", "no")
                    isdevice = elem.attrib.get("isdevice", "no")
                    ismechanical = elem.attrib.get("ismechanical", "no")
                    runnable = elem.attrib.get("runnable", "yes")
                    sampleof = elem.attrib.get("sampleof")
                    sourcefile = elem.attrib.get("sourcefile")

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

                    # SOUND – speakers
                    speakers_count = 0
                    sound_el = elem.find("sound")
                    if sound_el is not None:
                        channels = (sound_el.attrib.get("channels") or "").strip()
                        if channels.isdigit():
                            speakers_count = int(channels)
                    speakers_per_machine_ctr[str(speakers_count)] += 1

                    # CHIPS
                    cpu_count = 0
                    audio_count = 0
                    for chip in elem.findall("chip"):
                        ctype = (chip.attrib.get("type") or "").strip().lower()
                        if ctype == "cpu":
                            cpu_count += 1
                        elif ctype == "audio":
                            audio_count += 1

                    # DISPLAYS
                    display_count = len(elem.findall("display"))

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

                    # Per-machine canonical record (kept minimal for now)
                    machines_out[name] = {
                        "name": name,
                        "description": description,
                        "sourcefile": sourcefile,
                        "cloneof": cloneof,
                        "isbios": isbios,
                        "isdevice": isdevice,
                        "ismechanical": ismechanical,
                        "runnable": runnable,
                        "sampleof": sampleof,
                        "year": year_raw,
                        "manufacturer": manufacturer_raw,
                        "players": None if players_key == "unknown" else int(players_key),
                        "cpu_count": cpu_count,
                        "sound_chip_count": audio_count,
                        "display_count": display_count,
                        "speakers": speakers_count,
                    }

                    if max_records and total_machines >= max_records:
                        elem.clear()
                        break

                    elem.clear()
                    current_machine = None

    except ET.ParseError as e:
        log.error(f"XML parse error while reading {file_path.name}: {e}")
        return []

    parse_seconds = time.perf_counter() - start

    # Prepare ordered distributions
    years_dist = _sorted_numeric_keys_with_unknown_last(dict(years_ctr))
    manuf_dist = _sorted_alpha_with_unknown_last(dict(manuf_ctr))

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
    speakers_dist = _sort_numeric_str(dict(speakers_per_machine_ctr))


   # --- NEW: per-distribution sums for easy manual validation ---
    years_sum         = sum(years_dist.values())
    manufacturers_sum = sum(manuf_dist.values())
    players_sum       = sum(players_dist.values())
    cpus_sum          = sum(cpus_dist.values())
    sounds_sum        = sum(sounds_dist.values())
    displays_sum      = sum(displays_dist.values())
    speakers_sum      = sum(speakers_dist.values())
    # --- END NEW ---
 

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
                "sum": years_sum,  # NEW
            },
            "manufacturers": {
                "unique": len([k for k in manuf_dist.keys() if k != "unknown"]),
                "distribution": manuf_dist,
                "sum": manufacturers_sum,  # NEW
            },
            "players": {
                "distribution": players_dist,
                "sum": players_sum,  # NEW
            },
            "cpus_per_machine": {
                "distribution": cpus_dist,
                "sum": cpus_sum,  # NEW
            },
            "sound_devices_per_machine": {
                "distribution": sounds_dist,
                "sum": sounds_sum,  # NEW
            },
            "displays_per_machine": {
                "distribution": displays_dist,
                "sum": displays_sum,  # NEW
            },
            "speakers_per_machine": {
                "distribution": speakers_dist,
                "sum": speakers_sum,  # NEW
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
    result_list = [machines_sorted[k] for k in machines_sorted.keys()]
    debug_log(f"First 5 machines (canonical): {[m['name'] for m in result_list[:5]]}")
    return result_list
