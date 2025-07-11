from pathlib import Path
import xml.etree.ElementTree as ET
from collections import defaultdict
from logger import setup_logger
from history_metadata import classify_machine, is_valid_arcade_game

log = setup_logger()

def parse_mame_xml(file_path: Path, max_records: int = 0) -> list[dict]:
    """
    Parses the MAME XML file and extracts machine metadata.

    - Builds a dictionary of clone relationships.
    - Uses .ini-based classification to identify valid arcade games.
    - Preserves clones of valid parents even if their own classification is missing or invalid.

    Args:
        file_path (Path): Path to mame.xml
        max_records (int): Optional cap on how many machine entries to parse (0 = no limit)

    Returns:
        list[dict]: Filtered list of arcade/playable machines, clone-aware.
    """
    log.info(f"Starting MAME XML parsing: {file_path.name}" +
             (f" (max {max_records} records)" if max_records else " (no limit)"))

    machines = []
    all_machines = {}
    clones_by_parent = defaultdict(list)  # e.g. {"puckman": ["pacman", "pacmanf"]}

    current = None

    try:
        for event, elem in ET.iterparse(file_path, events=('start', 'end')):
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

    # --- Filtering Phase ---

    # Step 1: Valid arcade machines based on .ini classification
    valid_arcade = {name for name in all_machines if is_valid_arcade_game(name)}

    # Step 2: Promote clones of valid parents
    added_clones = set()
    for parent in list(valid_arcade):  # use a static list copy
        for clone in clones_by_parent.get(parent, []):
            if clone in all_machines and clone not in valid_arcade:
                valid_arcade.add(clone)
                added_clones.add(clone)

    # Step 3: Excluded machines (not valid, not a valid clone)
    excluded = []
    for name in all_machines:
        if name not in valid_arcade:
            excluded.append((name, classify_machine(name)))

    # Step 4: Build output list
    filtered_machines = [all_machines[name] for name in valid_arcade if name in all_machines]

    log.info(f"Included {len(filtered_machines)} machines after filtering")
    log.info(f"  - {len(added_clones)} were added as clones of valid parents")
    log.info(f"Excluded {len(excluded)} machines (not arcade/playable)")
    log.info("First 10 machines excluded (not valid or clone of valid):")
    for name, meta in excluded[:10]:
        log.info(f"  - {name}: {meta}")

    return filtered_machines
