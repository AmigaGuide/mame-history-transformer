from pathlib import Path
import xml.etree.ElementTree as ET
from collections import defaultdict
from logger import setup_logger
from history_metadata import classify_machine

log = setup_logger()

def parse_mame_xml(file_path: Path, max_records: int = 0) -> list[dict]:
    """
    Parses the MAME XML file and extracts machine metadata,
    filtering out non-arcade, non-playable entries using Gaming-History .ini files.

    Currently collects:
    - Machine name (from <machine> attribute)
    - Description (from <description> sub-element)
    - Builds a dictionary of clone relationships (indexed by cloneof target)

    Parameters:
        file_path (Path): Path to mame.xml
        max_records (int): Optional cap on how many machine entries to parse (0 = no limit)

    Returns:
        list[dict]: List of machines with basic metadata.
    """
    log.info(f"Starting MAME XML parsing: {file_path.name}" +
             (f" (max {max_records} records)" if max_records else " (no limit)"))

    machines = []
    clones_dict = defaultdict(list)
    skipped_unknown = 0
    skipped_non_arcade = 0
    excluded_unknown_list = []
    excluded_non_arcade_list = []
    parsed = 0

    try:
        for event, elem in ET.iterparse(file_path, events=('start', 'end')):
            if event == "start" and elem.tag == "machine":
                machine_name = elem.attrib.get("name", "Unknown")
                cloneof = elem.attrib.get("cloneof")
                current_machine = {"name": machine_name}

                # Apply classification filter
                classification = classify_machine(machine_name)

                if not classification:
                    skipped_unknown += 1
                    if len(excluded_unknown_list) < 10:
                        excluded_unknown_list.append(machine_name)
                    log.debug(f"Skipping '{machine_name}': not found in classification .ini files")
                    elem.clear()
                    continue

                if classification.get("game_status") != "Game" or classification.get("category") != "Arcade":
                    skipped_non_arcade += 1
                    if len(excluded_non_arcade_list) < 10:
                        excluded_non_arcade_list.append((machine_name, classification))
                    log.debug(f"Skipping '{machine_name}': classified as {classification}")
                    elem.clear()
                    continue

                if cloneof:
                    clones_dict[cloneof].append(machine_name)

            elif event == "end" and elem.tag == "description" and 'current_machine' in locals():
                current_machine["description"] = elem.text or ""

            elif event == "end" and elem.tag == "machine" and 'current_machine' in locals():
                machines.append(current_machine)
                parsed += 1
                if max_records and parsed >= max_records:
                    log.info(f"Reached parsing limit of {max_records} machines.")
                    break
                current_machine = None
                elem.clear()

    except ET.ParseError as e:
        log.error(f"XML parse error while reading {file_path.name}: {e}")
        return []

    log.info(f"Finished parsing MAME XML – {len(machines)} machines loaded")
    log.info(f"{len(clones_dict)} machines have at least one clone.")
    log.info(f"Excluded {skipped_unknown} machines (missing from classification)")
    log.info(f"Excluded {skipped_non_arcade} machines (not arcade/playable)")

    if excluded_unknown_list:
        log.info("First 10 machines excluded (not found in classification):")
        for name in excluded_unknown_list:
            log.info(f" - {name}")

    if excluded_non_arcade_list:
        log.info("First 10 machines excluded (not arcade/game):")
        for name, details in excluded_non_arcade_list:
            log.info(f" - {name}: {details}")

    return machines
