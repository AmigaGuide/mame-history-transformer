from pathlib import Path
import xml.etree.ElementTree as ET
from logger import setup_logger

log = setup_logger()

def parse_mame_xml(file_path: Path, max_records: int = 0) -> list[dict]:
    """
    Parses the MAME XML file and extracts machine metadata.

    Currently collects:
    - Machine name (from <machine> attribute)
    - Description (from <description> sub-element)

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

    try:
        for event, elem in ET.iterparse(file_path, events=('start', 'end')):
            if event == "start" and elem.tag == "machine":
                current_machine = {"name": elem.attrib.get("name", "Unknown")}

            elif event == "end" and elem.tag == "description" and current_machine is not None:
                current_machine["description"] = elem.text or ""

            elif event == "end" and elem.tag == "machine":
                if current_machine:
                    machines.append(current_machine)
                    if max_records and len(machines) >= max_records:
                        log.info(f"Reached parsing limit of {max_records} machines.")
                        break
                current_machine = None
                elem.clear()  # Free memory

    except ET.ParseError as e:
        log.error(f"XML parse error while reading {file_path.name}: {e}")
        return []

    log.info(f"Finished parsing MAME XML – {len(machines)} machines loaded")
    return machines
