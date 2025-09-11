# Data Folder

This folder contains both **required source files** and **generated artefacts** used during the TM470 *Lost in Translation* project.

## Source files (required at runtime)

These are **not committed to Git** (excluded via `.gitignore`) to avoid repository bloat and licensing issues.  
They must be supplied locally before running the pipeline:

- `mame.xml` - full MAME machine database (≈300 MB)  
- `history.xml` - Gaming-History trivia dataset (arcade systems and ports)  
- `*.ini` - Gaming-History classification INI files:
  - `[GAMING HISTORY] Game Or No Game.ini`
  - `[GAMING HISTORY] Machine Category.ini`
  - `[GAMING HISTORY] Machine Type.ini`

## Optional overrides

- `title_overrides.json` - local patch file (if present) used to override specific parent titles.  
  Each entry allows:
  - `description`: replacement title text to use instead of the raw MAME description  
  - `apply_if_unbalanced`: whether to apply only if the original title has unbalanced brackets (default `true`)  
  - `note`: a free-text reason for the override  

This is **not mandatory**, but provides a controlled way to correct problematic titles without altering source XML.

## Generated artefacts

These JSON files are created by the pipeline and are **excluded from version control** (via `.gitignore`):

- `encodings.json` - cached file encodings and version strings  
- `history_parsing_summary.json` - statistics and QA checks from parsing `history.xml`  
- `ini_parsing_summary.json` - coverage and diagnostics from INI classification files  
- `mame_parsing_summary.json` - statistics and QA checks from parsing `mame.xml`  
- `run_manifest.json` - per-run manifest with input/output paths, hashes, and timings  
- `transform_summary.json` - transformer audit (counts, anomalies, media stats, port coverage)

## Notes

- All **source XML and INI files must be supplied locally**; they are not shipped in this repository.  
- All **generated JSON artefacts** can be safely deleted; they will be recreated when the pipeline is rerun.  
