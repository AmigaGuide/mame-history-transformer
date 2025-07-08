from pathlib import Path
import xml.etree.ElementTree as ET
from collections import defaultdict
from logger import setup_logger

log = setup_logger()

def parse_mame_xml(file_path: Path, max_records: int = 0) -> list[dict]:
    """
    Parses the MAME XML file and extracts machine metadata.

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
    current_machine = None
    clones_dict = defaultdict(list)  # e.g. clones_dict["puckman"] = ["pacman", "pacmanf"]

    try:
        for event, elem in ET.iterparse(file_path, events=('start', 'end')):
            if event == "start" and elem.tag == "machine":
                machine_name = elem.attrib.get("name", "Unknown")
                cloneof = elem.attrib.get("cloneof")
                current_machine = {"name": machine_name}

                if cloneof:
                    clones_dict[cloneof].append(machine_name)

            elif event == "end" and elem.tag == "description" and current_machine is not None:
                current_machine["description"] = elem.text or ""

            elif event == "end" and elem.tag == "machine":
                if current_machine:
                    machines.append(current_machine)
                    if max_records and len(machines) >= max_records:
                        log.info(f"Reached parsing limit of {max_records} machines.")
                        break
                current_machine = None
                elem.clear()

    except ET.ParseError as e:
        log.error(f"XML parse error while reading {file_path.name}: {e}")
        return []

    log.info(f"Finished parsing MAME XML – {len(machines)} machines loaded")

    # Post-parsing clone reporting
    log.info(f"{len(clones_dict)} machines have at least one clone.")

    if "puckman" in clones_dict:
        puckman_clones = clones_dict["puckman"]
        log.info(f"Clones of 'puckman' ({len(puckman_clones)} total): {puckman_clones}")
    else:
        log.info("No clones found for 'puckman'.")

    return machines
