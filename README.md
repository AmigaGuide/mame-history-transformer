# TM470 – Lost in Translation Parser

This repository contains code developed for the Open University TM470 project:

**“Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation.”**

## Overview

This project parses and reconciles multiple sources:

- **MAME XML** - highly structured data describing arcade machines, ROMs, chips, devices, displays, controls, and clone relationships.  
- **Gaming-History XML** - semi-structured trivia including arcade-to-home conversion details under headings such as `PORTS`.  
- **Gaming-History INI files** - structured classification lists identifying whether a machine is a game, its category (e.g. Arcade, Computers, Consoles), and its hardware type.

The pipeline produces **ExoticA-ready JSON** for the *Lost in Translation* wiki, plus diagnostic summaries and manifests for quality assurance and reproducibility.

## Data flow (modules)

| Module                | Purpose                                                                 |
|-----------------------|-------------------------------------------------------------------------|
| `config.py`           | Global constants, including log level and schema versions               |
| `date_utils.py`       | Normalises date strings (e.g. fuzzy “198?” → `198X-XX-XX`)              |
| `encoding_utils.py`   | Detects file encodings using `chardet`                                  |
| `history_metadata.py` | Aggregates `.ini` metadata for classifications (game status, category, type) |
| `history_parser.py`   | Extracts and normalises `PORTS` from Gaming-History XML                 |
| `logger.py`           | Shared logging (file + console) with `[file::function]` prefixes        |
| `main.py`             | Entry point; orchestrates pipeline, validates encodings/versions, builds per-run manifest |
| `mame_parser.py`      | Streams MAME XML; extracts machines, years, manufacturers, ROM stats, disk/media flags, displays, controls, and parent/clone relations |
| `transformer.py`      | Final stage: applies selection rules, parses titles, formats manufacturers, chips, ROM/media/controls/displays, merges GH ports, and emits wiki-ready JSON |

## Current capabilities

- **Parent/clone handling**
  - Parents included if `.ini` → `game_status == "game"` and `category` contains Arcade.  
  - Clones linked under parents; their ports are unioned into the parent’s record.  

- **Title parsing & redirects**
  - Splits titles into numbered blocks + `global_version`.  
  - Builds wiki page names and sorted redirects.  
  - Title anomalies logged; optional overrides applied from `data/title_overrides.json`.  

- **Manufacturer formatting**
  - Splits on `/` outside parentheses, rejoins with `&`.  
  - Example: `ADK / SNK` → `ADK & SNK`.  

- **ROM/media block**
  - Multi-line: ROM count, total bytes (binary units), plus optional `Plus:` line for disks.  
  - Media normalisation (e.g. CD-ROM, DVD-ROM, GD-ROM, LaserDisc, CED, HDD, CompactFlash, SD card, NAND flash, USB storage, VHS tape).  
  - Multiplicities shown as `(Nx) Label`.  

- **Chips (CPU/Audio)**
  - Groups identical chips, frequency formatted to 3dp.  
  - Audio tail lines include “Requires additional samples”, “Audio Channel(s): N”, and “Speaker(s): N”.  

- **Displays**
  - Groups identical screens, outputs `(Nx)` form.  
  - Shows type, orientation, resolution, refresh Hz.  

- **Controls**
  - Player count, control types, ways (including half-ways), buttons vs reqbuttons.  
  - Human-readable labels, with pluralisation and “No Buttons” case handled.  

- **Ports (from GH XML)**
  - Extracts parent + clone ports with provenance.  
  - Preserves GH order and quirks (no silent deduplication).  
  - Wiki projection: one-line per port, embedding [Model] in title when present, provenance sentence when clone-sourced.  

- **Diagnostics & QA**
  - Summaries for encodings, INIs, MAME, GH XML, and transforms.  
  - Per-run manifest (`run_manifest.json`) records inputs, outputs, hashes, and timings.  
  - Title, media, platform, and publisher anomalies logged for audit.  

## Outputs

- `data/encodings.json` - cached encodings + version strings  
- `data/run_manifest.json` - per-run provenance (inputs, outputs, hashes, timings)  
- `data/mame_parsing_summary.json` - MAME totals, distributions, anomalies  
- `data/history_parsing_summary.json` - GH systems/ports metadata, anomalies, audit trails  
- `data/ini_parsing_summary.json` - INI coverage, duplicates, unknowns  
- `data/transform_summary.json` - transformer metrics, title/media/port stats  

- `output/mame_machines.json` - canonical per-machine MAME dataset  
- `output/mame_parent_index.json` - parent→clones and clone→parent maps  
- `output/gh_system_ports.json` - parsed GH systems + PORTS  
- `output/gh_ini_classifications.json` - per-machine INI classifications  
- `output/exotica_lit_raw_data.json` - full structured per-parent records (debug/validation)  
- `output/exotica_lit_wiki.json` - slimmed, wiki-ready JSON for ExoticA infoboxes  
- `output/exotica_wiki_pages_and_redirects.json` - page list, redirects, collisions  
