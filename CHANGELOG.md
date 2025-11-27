# Changelog

All notable changes to this project will be documented here.

## [Unreleased]

* `diff` command to compare outputs between two release versions (planned).
* CLI tab-completion support.
* Optional JSON schema validation on stamps.
* Performance metrics and timing summaries for each stage.

---

## [1.2.1] – 2025-11-27

### Added

* **Clone classification inheritance**
  - Clones now inherit their parent’s INI classification (`game_status`, `category`, `type`)
    when they do not appear in the GH INI files.
  - Ensures consistent metadata for clones in `exotica_lit_raw_data.json`,
    `exotica_lit_wiki.json`, and the wiki page/redirect generator.
  - No changes to `gh_ini_classifications.json` (remains a faithful reflection of
    the actual GH INI files, which appear to be parent-only in recent releases).

* **INI vs History coverage telemetry**
  - New detailed reporting in `transform_summary.json` showing:
    - Total GH systems with GH PORTS rows.
    - Counts of parents vs clones with ports.
    - Which systems lack INI coverage.
    - Parent-only nature of new GH INIs.
  - Helps detect when GH reduces or alters INI coverage between releases.

### Changed

* Transform stage now expands the INI map in-memory to include inherited clone classifications.
* Classification lookup (`classify`) now transparently uses inherited values without altering on-disk INI outputs.
* Cleaner separation between raw INI source data and transform-time classification semantics.

### Fixed

* Clones previously appeared with `"game_status": "unknown"` even when their
  parent had correct INI flags.
* Raw JSON outputs now correctly reflect inherited classification for all clones.

### Notes

* This change was triggered by the discovery that recent Gaming-History INI
  files have dropped clone entries entirely, supplying only parent classifications.
* Behaviour remains backward compatible: the canonical INI output is unchanged,
  and inherited values are applied only in the transform stage.

---

## [1.2.0] – 2025-11-09

### Added

* **Fixture-based golden testing**

  * Introduced new *subset-expectation framework* to verify parsed **Gaming-History trivia output** without requiring full schema equivalence.
  * Added reusable helpers:

    * `tests/util_json_subset.py` — flexible JSON subset matcher (`is_subset`, `_block_matches`) supporting partial text, label, and value checks.
    * `tests/util_expectations.py` — assertion helpers for validating parsed trivia sections and expected block types.
  * Created dedicated golden tests:

    * `tests/test_trivia_goldens.py` — verifies per-system subset expectations against `gh_system_trivia.json`.
    * `tests/test_trivia_schema_and_goldens.py` — integrates schema and subset validation, automatically discovering fixture cases.
  * Introduced example fixture set under `tests/fixtures/trivia_goldens/`:

    * `expected_subset.005.json`
    * `expected_subset.outrun.json`
    * `expected_subset.puckman.json`
    * `expected_subset.sf2j.json`
  * Fixture discovery now runs automatically and skips gracefully when empty; now all four systems pass under `pytest`.

* **Test reliability**

  * New low-level test file `tests/test_json_subset.py` to self-validate the subset utilities (7 green tests).
  * Parametrisation and discovery fixes eliminate previous “empty parameter set” warnings.
  * All trivia-related tests now execute cleanly with zero warnings or skips.

### Changed

* `test_trivia_schema_and_goldens.py` fixture discovery unified with `test_trivia_goldens.py` for consistency.
* JSON comparison logic improved to tolerate ordering differences, partial matches, and structured type checks (paragraph, pair, bullet list, numbered list).
* Improved indentation and consistency in golden fixtures for easier editing in Notepad++.
* Long-running trivia tests optimised for readability and selective runs using `-k trivia_goldens`.

### Fixed

* Removed redundant alias checks that broke working systems (e.g. “005” subset).
* Eliminated `PytestUnknownMarkWarning` caused by unregistered `@pytest.mark.order`.
* Resolved fixture path mismatches that previously caused `FileNotFoundError` or `JSONDecodeError`.

### Notes

* This release finalises the **testing infrastructure phase** for MAME-History-Transformer v2.
* The new subset-testing framework will safeguard future parsing logic changes by verifying that high-level section structures remain stable.
* All current tests (`pytest`) pass cleanly — **no warnings, no skips, 100 % success** — providing a verified baseline for the next parser iteration.

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
