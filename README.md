# MAME-History-Transformer

**Lineage:** this repository mirrors the full history of the TM470 EMA project (tag: `tm470-ema-2025`) and continues as a modular v2.

This repository contains code developed for the Open University TM470 project:

**“Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation.”**

---

## Overview

This project parses and reconciles multiple sources:

- **MAME XML** — structured data describing arcade machines, ROMs, chips, devices, displays, controls, and clone relationships.  
- **Gaming-History XML** — semi-structured trivia including arcade-to-home conversion details under headings such as `PORTS`.  
- **Gaming-History INI files** — structured classification lists identifying whether a machine is a game, its category (e.g. Arcade, Computers, Consoles), and its hardware type.

The pipeline produces **ExoticA-ready JSON** for the *Lost in Translation* wiki, plus diagnostic summaries and manifests for quality assurance and reproducibility.

---

## Status & approach

This v2 branch focuses on **schema-first, test-driven** correctness. I’ve used **ChatGPT** to help formalise JSON Schemas, add targeted pytest invariants, and align the code with those contracts. A refactor pass is planned to reduce duplication and improve module boundaries; for now the priority is correctness and repeatability.

Some tests are intentionally strict: they surface real upstream data anomalies (e.g. impossible display dimensions, `null` platform names) so they act as prompts for manual review rather than being silently normalised.

**Stamps (skip-unchanged):** stages now write a small JSON “stamp” under `data/.stamps/` capturing input file signatures and the tool version. When inputs and tool versions are unchanged, the stage is skipped. This keeps dev iterations fast while preserving reproducibility.

---

## Data flow (modules)

| Module | Purpose |
|---|---|
| `config.py` | Global constants, including log level and schema versions |
| `date_utils.py` | Normalises date strings (e.g. fuzzy `198?` → `198X-XX-XX`) |
| `encoding_utils.py` | Detects file encodings using `chardet` |
| `history_metadata.py` | Aggregates `.ini` metadata for classifications (game status, category, type) |
| `history_parser.py` | Extracts and normalises `PORTS` from Gaming-History XML |
| `logger.py` | Shared logging (file + console) with `[file::function]` prefixes |
| `main.py` | Entry point; orchestrates pipeline, validates encodings/versions, builds per-run manifest |
| `mame_parser.py` | Streams MAME XML; extracts machines, years, manufacturers, ROM stats, disk/media flags, displays, controls, and parent/clone relations |
| `transformer.py` | Final stage: applies selection rules, parses titles, formats manufacturers, chips, ROM/media/controls/displays, merges GH ports, and emits wiki-ready JSON |
| `utils/versions.py` | Centralised schema IDs/versions (summaries and outputs) and tool versions |
| `utils/stamps.py`   | Stamp helpers for skip-unchanged execution (pretty JSON + stable digest)  |


---

## Current capabilities

- **Parent/clone handling**  
  Parents included if `.ini` → `game_status == "game"` and `category` contains Arcade. Clones linked under parents; their ports are unioned into the parent’s record.

- **Title parsing & redirects**  
  Splits titles into numbered blocks + `global_version`. Builds wiki page names and sorted redirects. Title anomalies logged; optional overrides from `data/title_overrides.json`.

- **Manufacturer formatting**  
  Splits on `/` outside parentheses, rejoins with `&`. Example: `ADK / SNK` → `ADK & SNK`.

- **ROM/media block**  
  Multi-line: ROM count, total bytes (binary units), plus optional “Plus:” line for disks. Media normalisation (CD-ROM, DVD-ROM, GD-ROM, LaserDisc, CED, HDD, CompactFlash, SD card, NAND flash, USB storage, VHS tape). Multiplicities shown as `(Nx) Label`.

- **Chips (CPU/Audio)**  
  Groups identical chips; frequency formatted to 3dp. Audio tail lines include “Requires additional samples”, “Audio Channel(s): N”, and “Speaker(s): N”.

- **Displays**  
  Groups identical screens and outputs `(Nx)` form. Shows type, orientation, resolution, refresh Hz.

- **Controls**  
  Player count, control types, ways (including half-ways), buttons vs reqbuttons. Human-readable labels, with pluralisation and “No Buttons” handled. For entries with unknown control layouts but non-zero players, per-player placeholders are emitted to keep the schema consistent.

- **Ports (from GH XML)**  
  Extracts parent + clone ports with provenance. Preserves GH order and quirks (no silent deduplication). Wiki projection: one-line per port, embedding `[Model]` in title when present, plus a provenance sentence when clone-sourced.  
  *Note:* output always contains **both** `parent_source` and `clone_sources` keys to keep the schema fixed, even if one side has no categories.

- **Diagnostics & QA**  
  Summaries for encodings, INIs, MAME, GH XML, and transforms. Per-run manifest (`run_manifest.json`) records inputs, outputs, hashes, and timings. Title, media, platform, and publisher anomalies logged for audit.

---

## Outputs

- `data/encodings.json` — cached encodings + version strings  
- `data/run_manifest.json` — per-run provenance (inputs, outputs, hashes, timings)  
- `data/mame_parsing_summary.json` — MAME totals, distributions, anomalies  
- `data/history_parsing_summary.json` — GH systems/ports metadata, anomalies, audit trails  
- `data/ini_parsing_summary.json` — INI coverage, duplicates, unknowns  
- `data/transform_summary.json` — transformer metrics, title/media/port stats

- `output/mame_machines.json` — canonical per-machine MAME dataset  
- `output/mame_parent_index.json` — parent→clones map (and optional clone→parent reverse map)  
- `output/gh_system_ports.json` — parsed GH systems + PORTS  
- `output/gh_ini_classifications.json` — per-machine INI classifications  
- `output/exotica_lit_raw_data.json` — full structured per-parent records (debug/validation)  
- `output/exotica_lit_wiki.json` — slimmed, wiki-ready JSON for ExoticA infoboxes  
- `output/exotica_wiki_pages_and_redirects.json` — page list, redirects, collisions

---

### Summary JSON header (v1.0.1)

All four summary files include a unified header:

```json
"header": {
  "schema_id": "mht.<module>.summary",
  "schema_version": "1.0.1",
  "generated_at": "YYYY-MM-DDTHH:MM:SSZ",
  "versions": { /* data-source + tool versions; varies by file */ }
}
```

* **MAME** (`mht.mame.summary`): `versions.mame_xml_version`, `mame_build`, `mameconfig`, *(optionally)* `mame_parser_version`.
* **History** (`mht.history.summary`): `versions.gh_version`, `gh_date`, *(optionally)* `history_parser_version`.
* **INI** (`mht.ini.summary`): `versions.ini_generated_at` (+ consensus `mame_*` if present), *(optionally)* `ini_summary_version`.
* **Transform** (`mht.transform.summary`): timings duplicated in header (`started_utc`, `finished_utc`, `duration_seconds`) and `versions.transformer_version`.

Back-compat:

* We keep legacy blocks/keys for one cycle (e.g. MAME `invalid_displays_dropped` mirrored at `anomalies.dropped_displays`).
* Aliases are additive (e.g. History `total_systems` mirrors `systems_total`).

### Versioning

We use semantic versioning independently for **tools** and **schemas**:

* **Tools (code):** `MAJOR.MINOR.PATCH` (e.g. `transformer 1.0.1`).

  * PATCH: fixes/non-breaking behaviour
  * MINOR: new features, still backward compatible
  * MAJOR: breaking CLI/behaviour

* **Summary schemas:** `MAJOR.MINOR.PATCH` (current: **1.0.1**).

  * PATCH: additive fields/aliases (no removals)
  * MINOR: larger additive sections, still compatible
  * MAJOR: breaking (rename/remove without alias)

**Data-source versions** (MAME, Gaming-History, INIs) are always read from the artefacts, not hardcoded.

---

### Build caching (stamps)

Each stage writes a human-friendly stamp JSON under `data/.stamps/`, then compares it on the next run:

* `data/.stamps/mame.json` — for `mame_parser.py`
* `data/.stamps/history.json` — for `history_parser.py`
* `data/.stamps/ini.json` — for `history_metadata.py` (INI coverage)
* `data/.stamps/transform.json` — for `transformer.py`

**Stamp fields (pretty-printed):**

```json
{
  "schema_id": "mht.stage.stamp",
  "schema_version": "1.0.0",
  "generated_at": "YYYY-MM-DDTHH:MM:SSZ",
  "stage_id": "mht.stage.<name>",
  "tool_version": "1.0.1",
  "inputs": [
    {"path": "data/mame.xml", "size": 303629308, "size_h": "289.6 MiB",
     "mtime_ns": 1759160055721273900, "mtime_iso": "2025-09-29T15:34:15.721274Z"}
  ],
  "digest": "<sha256>"
}
```

* **Freshness rule:** a stage is skipped when the new digest matches the saved one.
* **What changes the digest?** input path/size/mtime, and the stage’s `tool_version` (from `src/mht/utils/versions.py`).
* **Housekeeping:** stamps are ignored by Git; delete a stamp file to force a rebuild of that stage.

---

## Schemas

Schemas live in `src/mht/contracts/` and are versioned using semantic versions:

- `exotica_lit_raw_data.schema.json` (`exotica_lit_raw_data`, **1.1.0**)  
- `exotica_lit_wiki.schema.json` (`exotica_lit_wiki`, **1.1.0**)  
- `exotica_wiki_pages_and_redirects.schema.json` (`exotica_wiki_pages_and_redirects`, **1.1.0**)  
- `gh_ini_classifications.schema.json` (`gh_ini_classifications`, **1.1.0**)  
- `gh_system_ports.schema.json` (`gh_system_ports`, **1.1.0**)  
- `mame_machines.schema.json` (`mame_machines`, **1.1.0**)  
- `mame_parent_index.schema.json` (`mame_parent_index`, **1.1.0**)

---

### Centralised versions

`src/mht/versions.py` is the single source of truth for:

* **Summary schema IDs/versions:** `SCHEMA_IDS`, `SCHEMA_INFO`
* **Tool versions:** `TOOL_VERSIONS`
* **Output dataset schemas:** `OUTPUT_SCHEMAS`

Usage example:

```python
from mht.versions import SCHEMA_IDS, schema_version, tool_version, output_schema

header = {
    "schema_id": SCHEMA_IDS["transform"],
    "schema_version": schema_version(SCHEMA_IDS["transform"]),
    "versions": {"transformer_version": tool_version("transformer")},
}

SCHEMA_ID_WIKI  = output_schema("wiki")["id"]
SCHEMA_VER_WIKI = output_schema("wiki")["version"]
```

---

## Tests

Run the full suite:

```bash
python -m pytest -q
