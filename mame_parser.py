"""
Filename: mame_parser.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Parses the MAME XML file to extract machine metadata, build clone relationships,
and apply classification filtering using data from Gaming-History .ini files.

Implements clone-aware logic to preserve child machines of valid arcade parents,
even if the clones lack independent classification. Returns a structured list
of machines suitable for JSON export.

This file is part of a student project and is not intended for commercial use.
"""

from pathlib import Path
import xml.etree.ElementTree as ET
from collections import defaultdict
import time
import logging

from config import LOG_LEVEL
from logger import setup_logger, debug_log
from history_metadata import classify_machine, is_valid_arcade_game

log = setup_logger(log_level=LOG_LEVEL)

def parse_mame_xml(file_path: Path, encodings: dict[str, str], max_records: int = 0) -> list[dict]:
    """
    Parses the MAME XML file and extracts machine metadata.

    - Builds a dictionary of clone relationships.
    - Uses .ini-based classification to identify valid arcade games.
    - Preserves clones of valid parents even if their own classification is missing or invalid.

    Args:
        file_path (Path): Path to mame.xml
        encodings (dict): Encodings dictionary (from main.py)
        max_records (int): Optional cap on how many machine entries to parse (0 = no limit)

    Returns:
        list[dict]: Filtered list of arcade/playable machines, clone-aware.
    """
    start_time = time.perf_counter()
    log.info(f"Starting MAME XML parsing: {file_path.name}" +
             (f" (max {max_records} records)" if max_records else " (no limit)"))

    mame_encoding = encodings["mame.xml"]

    machines = []
    all_machines = {}
    clones_by_parent = defaultdict(list)
    current = None

    try:
        with open(file_path, encoding=mame_encoding) as f:
            for event, elem in ET.iterparse(f, events=('start', 'end')):
                if event == "start" and elem.tag == "machine":
                    machine_name = elem.attrib.get("name", "Unknown")
                    cloneof = elem.attrib.get("cloneof")
                    current = {"name": machine_name}
                    if cloneof:
                        current["cloneof"] = cloneof
                        clones_by_parent[cloneof].append(machine_name)

                elif event == "end" and elem.tag == "description" and current is not None:
                    current["description"] = elem.text or ""

                elif event == "end" and elem.tag == "machine":
                    if current:
                        all_machines[current["name"]] = current
                        if max_records and len(all_machines) >= max_records:
                            log.info(f"Reached parsing limit of {max_records} machines.")
                            break
                    current = None
                    elem.clear()

    except ET.ParseError as e:
        log.error(f"XML parse error while reading {file_path.name}: {e}")
        return []

    log.info(f"Finished parsing MAME XML – {len(all_machines)} machines loaded")
    log.info(f"{len(clones_by_parent)} machines have at least one clone.")

    if log.isEnabledFor(logging.DEBUG) and "puckman" in clones_by_parent:
        puckman_clones = clones_by_parent["puckman"]
        debug_log(f"'puckman' has {len(puckman_clones)} clones: {puckman_clones}")

    # --- Filtering Phase ---

    valid_arcade = {name for name in all_machines if is_valid_arcade_game(name, encodings)}

    added_clones = set()
    for parent in list(valid_arcade):
        for clone in clones_by_parent.get(parent, []):
            if clone in all_machines and clone not in valid_arcade:
                valid_arcade.add(clone)
                added_clones.add(clone)

    excluded = []
    for name in all_machines:
        if name not in valid_arcade:
            excluded.append((name, classify_machine(name, encodings)))

    filtered_machines = [all_machines[name] for name in valid_arcade if name in all_machines]

    log.info(f"Included {len(filtered_machines)} machines after filtering")
    log.info(f"  - {len(added_clones)} were added as clones of valid parents")
    log.info(f"Excluded {len(excluded)} machines (not arcade/playable)")
    debug_log("First 10 machines excluded (not valid or clone of valid):")
    for name, meta in excluded[:10]:
        debug_log(f"  - {name}: {meta}")

    filter_time = time.perf_counter() - start_time
    log.info(f"Filtering completed in {filter_time:.2f} seconds")

    parse_time = time.perf_counter() - start_time
    log.info(f"MAME XML parsing completed in {parse_time:.2f} seconds")

    return filtered_machines
