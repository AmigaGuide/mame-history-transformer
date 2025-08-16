# Tools (Ad Hoc Analysis Utilities)

This folder contains standalone Python scripts and example JSON files used for exploratory analysis and demonstration during TM470 development. These scripts are **not part of the main application pipeline** but are useful for inspecting intermediate outputs, validating parsing logic, and preparing illustrative examples.

## Contents

### `platform_usage_report.py`
Generates a report of all unique `platform` names found in `gh_entries.json`, along with the list of `<system>` names each appears under.

- Helps audit inconsistent platform naming conventions in `history.xml`  
- Output saved as a dated `.txt` file in the main `/findings` directory  
- Run manually as needed, especially before preparing final JSON exports  

### `json_example.py`
Combines small hand-crafted example JSON inputs (MAME, Ports, Trivia) into composite outputs for demonstration purposes.

- Produces `json_example_before_trivia.json` (core game + ports)  
- Produces `json_example_puckman_with_trivia.json` (extended with trivia as a stretch goal)  
- Intended for communication with ExoticA (e.g. BuZz) to illustrate how structured JSON could feed wiki infoboxes  

### Example JSON files
These are mock datasets used as inputs/outputs for `json_example.py`:

- `json_example_mame_data.json`  
- `json_example_ports_data.json`  
- `json_example_trivia_data.json`  

They are **hand-authored examples** (not parsed directly from source XML) and exist to demonstrate schema choices before full automation.

---

These utilities and examples are preserved here for version tracking and transparency.  
All tools were written by Jason (XtC) Skelly during his TM470 project (Open University, 2025).
