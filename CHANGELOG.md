# Changelog

All notable changes to this project will be documented here.

## [Unreleased]

* `diff` command to compare outputs between two release versions (planned).
* CLI tab-completion support.
* Optional JSON schema validation on stamps.
* Performance metrics and timing summaries for each stage.

---

## [1.1.0] – 2025-10-28

### Added

* **CLI enhancements**

  * New root behaviour: running `python -m mht` now displays the **active release banner** and top-level help instead of executing the pipeline.
  * Each subcommand (`status`, `clean`, `fetch`, etc.) now prints a concise `[active] release = <ver>` banner at startup.
  * Parent groups (`incoming`, `releases`, `fetch`) now show **contextual help** instead of exiting with argparse errors.
  * New `--debug` flag for `fetch check` and `fetch download` to log HTTP probes (via `debug_log()`).
* **Fetch / provenance**

  * Improved remote probing: debug output clearly lists each attempted URL (e.g. `history282.zip`, `history282a.zip`, `history282b.zip`).
  * Duplicate downloads skipped unless `--overwrite` is provided.
  * Safe version detection from ZIP filenames ensures automatic routing to correct `releases/<ver>/archives`.
* **Ingest / provenance**

  * ZIP import now determines the correct target version automatically by inspecting filenames and build metadata.
  * All paths normalised via `as_posix()` for cross-platform consistency.
* **Tests**

  * Added new suite covering:

    * CLI root and help group behaviours (`test_cli_groups.py`, `test_cli_help.py`).
    * Active banner and fetch debug output (`test_active_banner.py`, `test_fetch_downloads.py`).
    * Ingest routing and provenance logic (`test_ingest_routing.py`).
    * Releases index generation (`test_releases_index.py`).
    * Stamp inputs and per-release encodings (`test_stamps_inputs.py`).
    * Version hint extraction (`test_version_hints.py`).
  * All tests now pass on Windows paths using `as_posix()` conversions.
* **Developer utilities**

  * `pyflakes` and `pytest` workflow tested and documented for refactoring/QA.
  * Optional `vulture`/`ruff` recommendations for dead-code detection.

### Changed

* `__main__.py` no longer runs the full pipeline by default; requires explicit `mht run`.
* CLI output fully emoji-free and consistent across platforms.
* `fetch.download()` and `fetch.check()` print more structured summaries (downloaded/skipped counts).
* `releases_index.py` now ensures all internal paths are relative to the `data/` root and always written using `as_posix()`.
* `stage_is_fresh()` now references per-release `encodings.json` instead of a global one.
* Tests and stamps updated for ZIP-only parsing (no extracted XML).

### Fixed

* False “stale” detection due to global `encodings.json` path.
* `cmd_ingest` no longer raises `AttributeError` for missing `no_extract` flag.
* History and INI stages correctly stamp their own ZIP inputs.
* `test_releases_index_builds_with_posix_paths` and related path checks now pass consistently.
* Pytest Windows temp directory edge cases resolved.

### Notes

* Versioned release workflow validated with **MAME 0.281 / GH 2.81** datasets.
* CLI behaviour now mirrors mature data pipelines (explicit stages, reproducible versions, per-release provenance).
* This update concludes the CLI stabilisation and provenance refactor phase.

## [1.0.2] - 2025-10-11
### Added
- `utils.stamps.stage_is_fresh()` helper to centralise stamp ceremony (ensures stamps dir, builds current stamp, loads previous, checks freshness).
- `utils.logger.maybe_log_progress()` used by MAME and History parsers.
- `utils/history_xml.py` module with event iterator, root-attr capture, and entry classification helpers.
- `utils/records.py` helpers for GH (`build_history_system_record`, `build_history_systems_sorted`).

### Changed
- **Parsers now act as orchestrators:**
  - `inputs/mame_parser.py` delegates header reads, core fields, players/controls/chips/displays/media/roms, counters and record assembly to utils.
  - `inputs/history_parser.py` delegates root capture, entry classification, text sectioning, PORTS handling, counters and record assembly.
- **Stamps:** MAME/History/INI/Transform stages now use `stage_is_fresh()` + `save_stamp` (replaces repeated `make_stamp/load_stamp/is_fresh` boilerplate).
- **Transform pipeline:** work moved to `transform/pipeline.py`; `transform/transformer.py` retained as a shim for compatibility.
- **Invariants:** warnings-only checks moved to `utils.validator` for both MAME and History.
- **Housekeeping:** progress logs consolidated via `maybe_log_progress`; minor import tidies.

### Fixed
- Duplicate `inputs=` argument in `history_metadata.py` stamp setup.
- Several small ordering issues in `history_parser.py` after refactor (initialisation before loop).

### Documentation
- README updated: module map reflects orchestrator architecture, stamps wrapper, and pipeline rename.
- ROADMAP updated: Phase 1 largely complete; stamps helper noted; next CLI/validator items clarified.
- Parser module docstrings refreshed to describe orchestrator role and side-effects.

### Notes
- Behaviour is unchanged; refactor focuses on structure, duplication reduction, and clarity.

## [1.0.1] - 2025-09-29
### Added
- Unified `header` in all summary JSONs (MAME, History, INI, Transform) with:
  - `schema_id`, `schema_version=1.0.1`, `generated_at`, and a `versions` block.
- Alias keys for backward compatibility:
  - MAME: `total_is_bios` mirrors `total_isbios`, `total_is_device` mirrors `total_isdevice`.
  - History: `total_systems`, `total_software`, `total_entries` mirror their `*_total` counterparts.
- `src/mht/versions.py` as the single source of truth for:
  - summary schema IDs/versions, tool versions, and output dataset schema IDs/versions.
- `qa.py` updated to read nested fields in the new headers and derive:
  - `anomalies_total` (sum of anomaly counts) and
  - `parents_dropped` (`eligible_parents - final_included`).

### Changed
- MAME, History, INI, and Transform writers now emit the `header` first for readability.
- `transformer.py` reads versions **header-first** from stage summaries, with legacy fallbacks.

### Fixed
- `transform_summary.json` no longer shows `null` for `mame_build`, `history_version`, or `history_date` when present in stage summaries.

### Deprecated
- MAME summary legacy `invalid_displays_dropped` is mirrored at `anomalies.dropped_displays` and will be retired in a future release.
- History summary `systems_total`, `software_total`, `entries_total` remain for compatibility but `total_*` is canonical going forward.
- Transform summary legacy top-level timing fields (`started_utc`, `finished_utc`, `duration_seconds`) are duplicated in `header` and may be removed later.

### Notes
- Repository rebranded to **mame-history-transformer** (v2) and code relocated under `src/mht/*`.
- Data source versions (MAME/GH/INI) are **always** taken from artefacts; only tool/schema versions are centralised.
- All changes in 1.0.1 are additive and backward-compatible.
