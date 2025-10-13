# MAME-History-Transformer

**Lineage:** this repository mirrors the full history of the TM470 EMA project (tag: `tm470-ema-2025`) and continues as a modular v2.

This repository contains code developed for the Open University TM470 project:

**“Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation.”**

---

## Overview

This project parses and reconciles multiple sources:

* **MAME XML** — structured data describing arcade machines, ROMs, chips, devices, displays, controls, and clone relationships.
* **Gaming-History XML** — semi-structured trivia including arcade-to-home conversion details under headings such as `PORTS`.
* **Gaming-History INI files** — structured classification lists identifying whether a machine is a game, its category (e.g. Arcade, Computers, Consoles), and its hardware type.

The pipeline produces **ExoticA-ready JSON** for the *Lost in Translation* wiki, plus diagnostic summaries and manifests for quality assurance and reproducibility.

---

## Status & approach

This v2 branch focuses on **schema-first, test-driven** correctness with a clear module boundary refactor:

* `mame_parser.py` and `history_xml_parser.py` are **orchestrators** — they stream XML and delegate all extraction, normalisation, counting and record assembly to focused helpers under `utils/` and `inputs/`.
* Small, reusable utilities remove duplication (XML accessors, counters/totals, progress logging, stamps).
* Pytest is green; the CLI validator reports successful.

Some tests are intentionally strict: they surface real upstream data anomalies (e.g. impossible display dimensions, `null` platform names) so they act as prompts for manual review rather than being silently normalised.

**Stamps (skip-unchanged):** stages write a small JSON “stamp” under `data/.stamps/` capturing input file signatures and the tool version. When inputs and tool versions are unchanged, the stage is skipped. This keeps dev iterations fast while preserving reproducibility.

**JSON writes:** `utils.io.write_json` pretty-prints and sorts keys by default for stable diffs. Pass `sort_keys=False` when you need to preserve insertion order.

### Refactor highlights (v2)

- **Parsers as orchestrators:** MAME and History XML now stream and delegate; heavy lifting lives under `utils/` and `inputs/`.
- **INI stage split:** `history_ini_parser.py` orchestrates only; parsing/normalisation moved to `utils/ini.py`, summary to `inputs/ini_summary.py`, classification to `utils/selection.py`, and the output map assembly to `utils/records.py`.
- **Stamps wrapper:** all stages use `utils.stamps.stage_is_fresh()` to cut boilerplate and keep behaviour identical.
- **Progress logging:** unified via `utils.logger.maybe_log_progress`.

---

## Data flow (modules)

| Module | Purpose |
|---|---|
| `mht/__main__.py`, `mht/cli.py` | CLI entrypoints and subcommands (`run`, `status`, `clean`, `validate`) |
| `main.py` | Compatibility entry that calls the pipeline (kept for convenience) |
| `inputs/mame_parser.py` | Streams MAME XML; orchestrates helpers; writes `mame_machines.json`, `mame_parent_index.json`, `mame_parsing_summary.json` |
| `inputs/history_xml_parser.py` | Streams Gaming-History XML; orchestrates sectioning + PORTS parsing; writes `gh_system_ports.json`, `history_parsing_summary.json` |
| `inputs/history_ini_parser.py` | **Orchestrator** for GH INIs (stamps + I/O only); delegates parsing/classification/summary to helpers |
| `inputs/ini_summary.py` | Pure summary builder for INI stage (`data/ini_parsing_summary.json`) |
| `transform/pipeline.py` | Final stage: selection + joins + title/manufacturer formatting + chips/ROM/media/controls/displays; writes ExoticA JSONs and `transform_summary.json` |
| `transform/transformer.py` | **Shim** that re-exports/forwards to `transform/pipeline.py` |
| `utils/mame_xml.py` | XML helpers for MAME: attribute/text accessors, yes/no mapping, event iterator, root attr capture, core field reads |
| `utils/history_xml.py` | XML helpers for GH: event iterator, root attr capture, entry classification, attribute/text utilities |
| `utils/ini.py` | INI helpers: header/version sniffing, section parsing, `<not available>` handling, small counters |
| `utils/controls.py`, `utils/displays.py`, `utils/chips.py`, `utils/media.py`, `utils/roms.py` | Focused extractors and formatters used by the parsers and transform |
| `utils/strings.py` | String utilities incl. bucketing keys for year/manufacturer |
| `utils/summaries.py` | Counter bucketing, per-entry/machine totals updates, ports result application, summary helpers |
| `utils/records.py` | Record assembly helpers (MAME machine; GH system; INI class map; sorted maps) |
| `utils/selection.py` | Selection/classification helpers (e.g., `classify_from_ini`) |
| `utils/validator.py` | Invariant checks (warnings-only) for MAME and GH parsing |
| `utils/logger.py` | Logging setup + `maybe_log_progress` helper |
| `utils/headers.py` | Unified JSON summary header builder |
| `utils/io.py` | Safe JSON read/write (atomic, pretty) |
| `utils/stamps.py` | Stamp helpers, incl. `stage_is_fresh()` wrapper |
| `utils/versions.py` | Schema IDs/versions and tool versions (single source of truth) |
| `inputs/history_ports.py`, `inputs/history_text.py`, `inputs/history_constants.py` | GH-specific sectioning, PORTS parsing and constants |

---

## Current capabilities

* **Parent/clone handling**
  Parents included if `.ini` → `game_status == "game"` and `category` contains Arcade. Clones linked under parents; their ports are unioned into the parent’s record.

* **Title parsing & redirects**
  Splits titles into numbered blocks + `global_version`. Builds wiki page names and sorted redirects. Title anomalies logged; optional overrides from `data/title_overrides.json`.

* **Manufacturer formatting**
  Splits on `/` outside parentheses, rejoins with `&`. Example: `ADK / SNK` → `ADK & SNK`.

* **ROM/media block**
  Multi-line: ROM count, total bytes (binary units), plus optional “Plus:” line for disks. Media normalisation (CD-ROM, DVD-ROM, GD-ROM, LaserDisc, CED, HDD, CompactFlash, SD card, NAND flash, USB storage, VHS tape). Multiplicities shown as `(Nx) Label`.

* **Chips (CPU/Audio)**
  Groups identical chips; frequency formatted to 3dp. Audio tail lines include “Requires additional samples”, “Audio Channel(s): N”, and “Speaker(s): N”.

* **Displays**
  Groups identical screens and outputs `(Nx)` form. Shows type, orientation, resolution, refresh Hz.

* **Controls**
  Player count, control types, ways (including half-ways), buttons vs reqbuttons. Human-readable labels, with pluralisation and “No Buttons” handled. For entries with unknown control layouts but non-zero players, per-player placeholders are emitted to keep the schema consistent.

* **Ports (from GH XML)**
  Extracts parent + clone ports with provenance. Preserves GH order and quirks (no silent deduplication). Wiki projection: one-line per port, embedding `[Model]` in title when present, plus a provenance sentence when clone-sourced.
  *Note:* output always contains **both** `parent_source` and `clone_sources` keys to keep the schema fixed, even if one side has no categories.

* **Diagnostics & QA**
  Summaries for encodings, INIs, MAME, GH XML, and transforms. Per-run manifest (`run_manifest.json`) records inputs, outputs, hashes, and timings. Title, media, platform, and publisher anomalies logged for audit.

---

## Outputs

* `data/encodings.json` — cached encodings + version strings

* `data/run_manifest.json` — per-run provenance (inputs, outputs, hashes, timings)

* `data/mame_parsing_summary.json` — MAME totals, distributions, anomalies

* `data/history_parsing_summary.json` — GH systems/ports metadata, anomalies, audit trails

* `data/ini_parsing_summary.json` — INI coverage, duplicates, unknowns

* `data/transform_summary.json` — transformer metrics, title/media/port stats

* `output/mame_machines.json` — canonical per-machine MAME dataset

* `output/mame_parent_index.json` — parent→clones map (and optional clone→parent reverse map)

* `output/gh_system_ports.json` — parsed GH systems + PORTS

* `output/gh_ini_classifications.json` — per-machine INI classifications

* `output/exotica_lit_raw_data.json` — full structured per-parent records (debug/validation)

* `output/exotica_lit_wiki.json` — slimmed, wiki-ready JSON for ExoticA infoboxes

* `output/exotica_wiki_pages_and_redirects.json` — page list, redirects, collisions

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

* **MAME** (`mht.mame.summary`): `versions.mame_xml_version`, `mame_build`, `mameconfig`, `mame_parser_version`.
* **History** (`mht.history.summary`): `versions.gh_version`, `gh_date`, `history_parser_version`.
* **INI** (`mht.ini.summary`): `versions.ini_generated_at` (+ consensus `mame_*` if present), `ini_summary_version`.
* **Transform** (`mht.transform.summary`): timings are **top-level** (`started_utc`, `finished_utc`, `duration_seconds`). `versions.transformer_version` is in the header.

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

* `data/.stamps/mame.json` — for `inputs/mame_parser.py`
* `data/.stamps/history.json` — for `inputs/history_xml_parser.py`
* `data/.stamps/ini.json` — for `inputs/history_ini_parser.py`
* `data/.stamps/transform.json` — for `transform/pipeline.py`

We use a convenience wrapper:

```python
from mht.utils.stamps import stage_is_fresh, save_stamp

fresh, stamp_path, current_stamp = stage_is_fresh(
    "transform.json",
    schema_id="mht.stage.transform",
    tool="transformer",
    inputs=[...],
)
if fresh:
    # skip work
    return True

# ...do work...

save_stamp(stamp_path, current_stamp)
```

**Freshness rule:** a stage is skipped when the new digest matches the saved one.
**What changes the digest?** input path/size/mtime, and the stage’s `tool_version`.
**Housekeeping:** stamps are ignored by Git; delete a stamp file to force a rebuild.

---

## Schemas

Schemas live in `src/mht/contracts/` and are versioned using semantic versions:

* `exotica_lit_raw_data.schema.json` (`exotica_lit_raw_data`, **1.1.0**)
* `exotica_lit_wiki.schema.json` (`exotica_lit_wiki`, **1.1.0**)
* `exotica_wiki_pages_and_redirects.schema.json` (`exotica_wiki_pages_and_redirects`, **1.1.0**)
* `gh_ini_classifications.schema.json` (`gh_ini_classifications`, **1.1.0**)
* `gh_system_ports.schema.json` (`gh_system_ports`, **1.1.0**)
* `mame_machines.schema.json` (`mame_machines`, **1.1.0**)
* `mame_parent_index.schema.json` (`mame_parent_index`, **1.1.0**)

---

### Centralised versions

`src/mht/utils/versions.py` is the single source of truth for:

* **Summary schema IDs/versions:** `SCHEMA_IDS`, `SCHEMA_INFO`
* **Tool versions:** `TOOL_VERSIONS`
* **Output dataset schemas:** `OUTPUT_SCHEMAS`

Usage example:

```python
from mht.utils.versions import SCHEMA_IDS, schema_version, tool_version, output_schema

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
```

## CLI quick start

```bash
# Full incremental pipeline (same as running main.py)
python -m mht

# Or explicit
python -m mht run

# See which stages are fresh/stale by stamp
python -m mht status

# Safe clean (preview only)
python -m mht clean --outputs --stamps --data-summaries --dry-run

# Confirmed clean (no prompt)
python -m mht clean --outputs --stamps --data-summaries --yes
```

## Validate outputs against schemas

Validate generated JSONs in `output/` against the JSON Schemas in `src/mht/contracts/`:

```bash
# Validate all (raw, wiki, pages)
python -m mht validate

# Validate a subset
python -m mht validate --only wiki pages
```

The validator uses paths from `mht.utils.paths` (single source of truth) and reports any schema or document issues with clear messages.
