# Roadmap (v2)

This roadmap reflects the current architecture and long-term development path of MAME-History-Transformer (MHT).

---

## Phase 1 — Structure & Contracts (complete)

### ✓ Unified summary headers

All stages now emit a standard header (`schema_id`, `schema_version`, `generated_at`, `versions`).

### ✓ Centralised version management

`mht/utils/versions.py` now tracks:

* Schema IDs
* Schema versions
* Tool versions
* Output dataset schema versions

### ✓ Per-release provenance directories

Each release version now has its own:

* `archives/` (ZIPs ingested via `mht ingest`)
* `.stamps/` (checksum + input provenance per stage)
* `encodings.json` (per-file encoding + version caches)
* `outputs/`
* `summaries/`

### ✓ Parser refactor into orchestrators

`mame_parser.py`, `history_xml_parser.py`, and `history_ini_parser.py` now delegate to structured helpers in `utils/`.

### ✓ ZIP-only pipeline

All input is streamed directly from ZIP archives.
No temporary extraction.

### ✓ Logging and progress framework

Common helpers:

* `maybe_log_progress()`
* `debug_log()`
* Normalised `[file::function]` debug tags
* Consistent `[active] release = …` banners

### ✓ Documentation & Tests Updated

README, CHANGELOG, CLI help screens, and the pytest suite are aligned with the v2 architecture.

---

## Phase 2 — CLI & Orchestration (stable)

### ✓ Core `mht` CLI groups

Pipeline

* `mht run` — explicit full pipeline run (never implicit)
* `mht validate` — schema validation for outputs
* `mht clean` — safe deletion with `--dry-run` and `--yes`

Releases

* `mht releases list`
* `mht releases set <ver>`
* `mht releases prune`
* Automatic `releases_index.json` (paths normalised)

Incoming / Fetch

* `mht fetch probe` — online discovery of new versions
* `mht fetch download` — download paired ZIPs
* `mht incoming scan` — preview incoming archives
* `mht ingest` — classify and place archives into a release directory

### ✓ Usability Enhancements

* Root invocation (`python -m mht`) prints help and active release
* Parent groups (`mht releases`, `mht fetch`, `mht incoming`) show contextual help
* Optional `--debug` shows every attempted fetch URL
* All commands banner the active release (except root)

### Next CLI tasks (remaining for Phase 2)

* Optional `--json` output for `mht status`
* Improve error text when ZIPs or stamps are missing
* Optional `mht run --limit <n>` to parse only a subset for debugging

---

## Phase 3 — Validation, Invariants, and Extended Trivia Parsing (in progress)

This phase reflects your current work.

### ✓ Extended Trivia Parsing (non-PORTS sections)

Trivia parsing now includes:

* Paragraph detection
* Bullet lists
* Dash lists
* Pairs (`a : b`, or hyphen separators)
* Preambles before lists
* Multi-paragraph structures
* Bracket-aware separators
* Various edge cases (translation text, mixed formats)

This is now part of the core Trivia extraction and is no longer listed as a “future feature”.

### ✓ Expected subsets for Trivia

Test fixtures for Trivia (e.g. *puckman*, *sf2j*, *005*) are now aligned with new structural rules.

### ✓ Manual validation command

`python -m mht validate` now:

* Performs JSON Schema validation
* Validates gh_system_trivia.json
* Shows progress for multi-file validation
* Is not run automatically as part of `mht run`

### ◻ Schema + invariant tests

Remaining tasks:

* Validate parent/clone and counter consistency
* Validate PORTS coverage, platform categories, and residue
* Reinforce schema completeness via CI-friendly tests
* Add INI-vs-History coverage reporting (parents vs clones, missing entries, unknowns)

### ◻ Performance guardrails

Future part of Phase 3:

* Record basic wall-clock times in stage summaries
* Track potential slow regressions (useful for large GH releases)

---

## Phase 4 — Nice-to-haves (planned)

### ◻ Enhanced Trivia rendering / presentation

Optional improvements which build on the *existing* Trivia parser:

* Convert logical lists or pairs into HTML-ready table structures
* Improved cross-release comparison of Trivia formatting
* Render Staff or Versions sections in table-like formats
* Optional inclusion of “raw-text” Trivia output for diffing

### ◻ `mht diff` (cross-release diff engine)

Compare outputs or summaries between releases, e.g.:

* Parent/clone changes
* Port coverage differences
* Trivia structure evolution
* Machine counts per year/manufacturer

This only makes sense once Trivia & PORTS parsing is completely stable.

### ◻ Optional YAML output

Generate YAML variants of JSON outputs for human-readable diffs.

### ◻ Static HTML viewer (read-only)

A small static HTML interface to browse:

* Summaries
* Headers
* Trivia blocks
* Version metadata
* Port tables

### ◻ Anomaly whitelist

Let users suppress repetitive or harmless anomalies (e.g. `bitmap_printer`, odd spacing patterns), while preserving full audit logs.

---

## Maintenance Checklist (before v1.1.0)

* [x] Update README/CHANGELOG
* [x] Ensure all CLI help screens are accurate
* [x] Full end-to-end run on 0.281 and 0.282 data sets
* [x] New manual validation workflow
* [x] Restore green pytest across all platforms
* [ ] Run pyflakes/ruff cleanup (unused imports etc.)
* [ ] Tag release `v1.1.0`
* [ ] Rebuild `releases_index.json` for full history

### To Do

* Continue monitoring GH INI structure (parent-only vs parent+clone) across future releases.
* If GH expand or change INI semantics again, update inheritance logic accordingly.
* Extend coverage invariants to warn when History XML systems gain/drops across versions.
