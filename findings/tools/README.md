# Tools (Ad Hoc Analysis Utilities)

This folder contains standalone Python scripts used for exploratory analysis and diagnostic auditing during TM470 development. These scripts are **not part of the main application pipeline** but are useful for inspecting intermediate outputs and identifying inconsistencies in source data.

## Contents

### `platform_usage_report.py`
Generates a report of all unique `platform` names found in `gh_entries.json`, along with the list of `<system>` names each appears under.

- Helps audit inconsistent platform naming conventions in `history.xml`
- Output saved as a dated `.txt` file in the main `/findings` directory
- Run manually as needed, especially before preparing final JSON exports

---

These utilities are preserved here for version tracking and transparency. All tools were written by Jason (XtC) Skelly during his TM470 project (Open University, 2025).
