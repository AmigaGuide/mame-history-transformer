# MAME-History-Transformer

**Lineage:** this repository mirrors the full history of the TM470 EMA project (tag: `tm470-ema-2025`) and continues as a modular v2.

This repository contains code developed for the Open University TM470 project:

**“Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation.”**

---

## Overview

This project streams and reconciles multiple sources:

* **MAME XML** — structured data describing arcade machines, ROMs, chips, devices, displays, controls, and clone relationships.
* **Gaming-History XML** — semi-structured trivia that includes arcade-to-home conversion details (e.g., `PORTS` sections).
* **Gaming-History INI files** — classification lists indicating whether a machine is a game, its category (Arcade/Computers/Consoles), and hardware type.

The pipeline produces **ExoticA-ready JSON** for the *Lost in Translation* wiki, plus diagnostic summaries and provenance for reproducibility.

---

## Status & approach

v2 focuses on **schema-first, test-driven** correctness with clear module boundaries:

* `mame_parser.py` and `history_xml_parser.py` are **orchestrators**: they stream XML and delegate extraction/normalisation/assembly to focused helpers under `utils/` and `inputs/`.
* Reusable utilities remove duplication (XML accessors, counters/totals, progress logging, stamps).
* Pytest is green; the CLI validator reports successful.

Some tests are intentionally strict: they surface upstream anomalies (e.g., odd display sizes, unknown platforms) as prompts for manual review rather than silently “fixing” data.

---

## What’s new in v2 (highlights)

* **ZIP-only pipeline:** stages read directly from staged archives under `data/releases/<ver>/archives/`. No temporary extraction required.
* **Per-release provenance:** stamps and encodings are stored per release:

  * `data/releases/<ver>/.stamps/*.json`
  * `data/releases/<ver>/encodings.json`
* **CLI behaviour:**

  * Running `python -m mht` shows **active release** and **help** (it no longer runs the pipeline).
  * Subcommands print a short **active release banner** (suppressed for the root help).
  * Parent groups (`incoming`, `releases`, `fetch`) show contextual help instead of argparse errors.
  * `fetch check|download` accept `--debug` to log every remote probe (e.g., `history282.zip`, `history282a.zip`, `history282b.zip`).
* **Path normalisation:** JSON and stamps record paths with `as_posix()` for stable, cross-platform diffs.
* **Releases index:** `data/releases_index.json` summarises staged archives, outputs, summaries and encodings per release.

---

## Data layout (per release)

```
data/
  releases/
    0281/
      archives/      # staged ZIPs (mame0281*.zip, history281*.zip, etc.)
      outputs/       # generated dataset JSONs
      summaries/     # parsing and transform summaries
      .stamps/       # per-stage stamps (mame.json, history.json, ini.json, transform.json)
      encodings.json # per-release encoding/version cache
  releases_index.json
  current_version.txt
```

---

## Module map

| Module                          | Purpose                                                                                                            |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `mht/__main__.py`, `mht/cli.py` | CLI entry points and subcommands (`run`, `status`, `clean`, `validate`, `incoming`, `releases`, `ingest`, `fetch`) |
| `main.py`                       | Compatibility entry that calls the pipeline (`mht run` is preferred)                                               |
| `inputs/mame_parser.py`         | Streams MAME XML; writes `mame_machines.json`, `mame_parent_index.json`, `mame_parsing_summary.json`               |
| `inputs/history_xml_parser.py`  | Streams GH XML; writes `gh_system_ports.json`, `history_parsing_summary.json`                                      |
| `inputs/history_ini_parser.py`  | Orchestrates GH INIs from the ZIP; writes `gh_ini_classifications.json`, `ini_parsing_summary.json`                |
| `transform/pipeline.py`         | Final joins + projections; writes ExoticA JSONs and `transform_summary.json`                                       |
| `transform/transformer.py`      | Shim forwarding to `transform/pipeline.py`                                                                         |
| `utils/*`                       | XML helpers, selection, record assembly, counters, logging, stamps, IO, headers, versions                          |
| `provenance/*`                  | Fetch, ingest, peeking archives, releases index                                                                    |

---

## Outputs

* `data/releases/<ver>/outputs/…`

  * `mame_machines.json`
  * `mame_parent_index.json`
  * `gh_system_ports.json`
  * `gh_ini_classifications.json`
  * `exotica_lit_raw_data.json`
  * `exotica_lit_wiki.json`
  * `exotica_wiki_pages_and_redirects.json`
* `data/releases/<ver>/summaries/…`

  * `mame_parsing_summary.json`
  * `history_parsing_summary.json`
  * `ini_parsing_summary.json`
  * `transform_summary.json`

---

## Stamps (skip-unchanged)

Each stage maintains a per-release stamp capturing input file signatures and tool version:

* `data/releases/<ver>/.stamps/mame.json`
* `data/releases/<ver>/.stamps/history.json`
* `data/releases/<ver>/.stamps/ini.json`
* `data/releases/<ver>/.stamps/transform.json`

Convenience wrapper:

```python
from mht.utils.stamps import stage_is_fresh, save_stamp

fresh, stamp_path, current = stage_is_fresh(
    "mame.json",
    schema_id="mht.stage.mame",
    tool="mame_parser",
    inputs=[zip_path, encodings_path],
)
if fresh:
    return True

# … do work …

save_stamp(stamp_path, current)
```

A stage is “fresh” when the new digest matches the saved one. The digest changes when any input path/size/mtime or the `tool_version` changes.

---

## Schemas & versions

* **Summary schemas** (IDs/versions) and **tool versions** are defined in `mht.utils.versions`.
* **Output dataset schemas** live under `src/mht/contracts/` and are versioned (semantic, additive for MINOR/PATCH).

Data-source versions (MAME build, GH version/date, INI versions) are **read from artefacts** and echoed in summary headers.

---

## CLI

### Root and help

```bash
# Root: prints active banner + commands (does not run the pipeline)
python -m mht

# Help for any group/command
python -m mht -h
python -m mht releases -h
python -m mht fetch -h
```

### Releases

```bash
# Markers and paths
python -m mht releases list
python -m mht releases set 0281
python -m mht releases info        # uses active release by default
python -m mht releases index       # (re)build data/releases_index.json
python -m mht releases prune --keep 2 --yes
python -m mht releases gc
```

### Incoming and ingest

```bash
# See what’s in data/incoming
python -m mht incoming scan
# Verify ZIPs without moving
python -m mht incoming verify --version 0281
# Adopt a specific ZIP into a release
python -m mht incoming adopt data/incoming/mame0281lx.zip --version 0281

# Automatically route ZIPs from data/incoming to the right release
python -m mht ingest                  # uses active release if needed
python -m mht ingest --version 0281   # force a target release
```

### Fetch (providers)

```bash
# Probe availability of the next versions (MAME + GH)
python -m mht fetch check
python -m mht fetch check --debug     # log each attempted URL variant

# Download when both are available (skips existing unless --overwrite)
python -m mht fetch download
python -m mht fetch download --debug
```

### Pipeline, status, clean, validate

```bash
# Explicit run (root no longer runs the pipeline)
python -m mht run

# Stamp freshness by stage for the active (or given) release
python -m mht status
python -m mht status --version 0281

# Clean artefacts
python -m mht clean --outputs --stamps --data-summaries --dry-run
python -m mht clean --outputs --stamps --data-summaries --yes

# Validate outputs against schemas
python -m mht validate
python -m mht validate --only wiki pages
```

---

## Tests & QA

Run the full suite:

```bash
python -m pytest -q
```

Static analysis (optional, recommended):

```bash
# Pyflakes
python -m pip install pyflakes
pyflakes src tests

# Ruff (optional, combines lint/format rules and can catch some dead code)
python -m pip install ruff
ruff check src tests
```

JSON writes use `utils.io.write_json` which pretty-prints and sorts keys by default for stable diffs (pass `sort_keys=False` to preserve order).

---

## Notes

* Paths written into JSON are normalised with `as_posix()` for consistent diffs on Windows/macOS/Linux.
* Title overrides (when needed) live in `data/title_overrides.json`.
* The project prefers additive, non-breaking schema evolution. Legacy aliases are kept for at least one cycle when fields move or are renamed.
