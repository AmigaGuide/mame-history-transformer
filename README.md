# TM470 - Lost in Translation Parser

This repository contains code developed for the Open University TM470 project:

**"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."**

## Overview

This project parses and reconciles two sources:

- **MAME XML** — structured data describing arcade machines, ROMs, devices and clone relationships.
- **Gaming-History XML** — semi-structured trivia including arcade-to-home conversion details under headings such as `PORTS`.
- **Gaming-History INI** – Raw list of MAME machine names based on categories such 'Game' or 'No Game' and what type of hardware is being emulated.

The pipeline produces **reader-ready JSON** for ExoticA’s *Lost in Translation* wiki infoboxes, plus diagnostic summaries for quality assurance.

## Data flow (modules)

| Module                | Purpose                                                                 |
|-----------------------|-------------------------------------------------------------------------|
| `main.py`             | Entry point; coordinates runs and stage dependencies                    |
| `mame_parser.py`      | Streams MAME XML; extracts machines, years, manufacturers, ROM stats, disk flags/regions, and parent/clone relations |
| `history_metadata.py` | Aggregates `.ini` metadata for classifications (game status, category, type) |
| `history_parser.py`   | Extracts and normalises `PORTS` from Gaming-History XML                 |
| `encoding_utils.py`   | Detects/caches file encodings using `chardet`                           |
| `logger.py`           | Configures logging                                                       |
| `config.py`           | Global constants (including log level)                                  |
| `transformer.py`      | Final coordinator: applies selection rules, parses titles, formats manufacturers, builds ROM block, normalises media, and emits wiki-ready JSON and summaries |

## Current capabilities

- **Selection rules (parents only):**
  - Keep parents where `.ini` says `game_status == "game"` and `category` includes `Arcade`.
  - Include clones only for the titles table in each parent’s record (for reference).

- **Title parsing & redirects:**
  - Splits titles into numbered `titleN`, `subtitleN`, `versionN` with a single `global_version`.
  - Builds a canonical wiki page name from `title1[: subtitle1]`.
  - Emits a sorted pages map and case-insensitive redirects (with conflict detection).

- **Manufacturer display (house style):**
  - Split on `/` **only when outside parentheses**, trim each part, then join with **`&`**:
    - `ADK / SNK` → `ADK & SNK`
    - `Tatsumi (Atari/Namco/Taito license) / Taito` → `Tatsumi (Atari/Namco/Taito license) & Taito`
  - Single, reusable `join_with_ampersand()` to keep prose consistent.

- **ROMs block (infobox ready):**
  - Line 1: plural-aware ROM count, e.g. `6 ROMs`.
  - Line 2: byte total with binary unit (KiB/MiB/GiB), e.g. `7,413,760 bytes (7.07 MiB)`.
  - Line 3: shown **only** when `disk_required == "yes"` → `Plus: <media>`.
  - Multi-media join with `&` and optional precedence ordering.

- **Media normalisation (from MAME internal device names):**
  - Maps raw device paths/tokens to tasteful labels:
    - **CD-ROM**, **DVD-ROM**, **GD-ROM**, **LaserDisc**, **Capacitance Electronic Disc (CED)**,
      **Hard disk**, **CompactFlash card**, **Secure Digital card**, **NAND flash**, **USB storage**, **VHS tape**.
  - Ignores non-media tokens (e.g. `runtime`, `install`, `disks`, `cycraft`).
  - Supports multiple media per parent and de-dupes per parent for counting.

- **Diagnostics & audit:**
  - `media_label_counts` and `parents_with_any_media` (parents only).
  - **Ignored media devices** section listing unmapped raw tokens (top N).
  - Title anomaly buckets (e.g. unbalanced brackets, odd separators).

## Outputs

- `output/exotica_lit_wiki.json`  
  Wiki-ready JSON with a header (versions, generated_at, schema) and a `games` map.  
  Key fields per parent include:
  - `wiki_page_name`
  - `description` (numbered title fields + global_version)
  - `manufacturer` (joined with `&`)
  - `roms_display` (2-3 line block as above)
  - `mame_titles` (parent + clones table rows for reference)
  - `.ini` classifications and MAME flags (isbios, isdevice, ismechanical)

- `output/exotica_wiki_pages_and_redirects.json`  
  Sorted pages list, page→machine map, redirects, and collision/conflict stats.

- `data/transform_summary.json`  
  Run timings, version sources, selection/filter counts, title anomalies, media counts, and ignored media audit.
