# Findings – Tools

This folder contains **standalone Python scripts and example JSON files** used for exploratory analysis during TM470 development.  
They are **not part of the main application pipeline**, but support:

- Inspecting intermediate outputs  
- Validating parsing logic  
- Preparing illustrative examples for communication with ExoticA (e.g. BuZz)  

## Contents

### `platform_usage_report.py`
Generates a report of all unique `platform` names found in `gh_entries.json`, along with the list of `<system>` names each appears under.

- Audits inconsistent platform naming conventions in `history.xml`  
- Outputs a dated `.txt` file to the main `/findings` directory  
- Run manually as needed, especially before preparing final JSON exports  

### `json_example.py`
Combines small hand-crafted JSON inputs (MAME, Ports, Trivia) into composite outputs for demonstration.

- Produces `json_example_before_trivia.json` (core game + ports)  
- Produces `json_example_puckman_with_trivia.json` (extended with trivia, stretch goal)  
- Used to show how structured JSON could feed ExoticA wiki infoboxes  

### Example JSON files
Mock datasets used as inputs/outputs for `json_example.py`:

- `json_example_mame_data.json`  
- `json_example_ports_data.json`  
- `json_example_trivia_data.json`  

These are **hand-authored examples** (not parsed from source XML).  
They demonstrate schema choices prior to full automation.

## Notes

- All utilities and examples here were written by Jason (XtC) Skelly during his TM470 project (Open University, 2025).  
- Preserved for version tracking and transparency.
