# Changelog

All notable changes to this project will be documented here.

## [Unreleased]

### Planned or under consideration

- CLI tab-completion support.
- Optional JSON schema validation for stamps.
- Further per-stage performance reporting.
- Historical snapshot compatibility checks for releases processed before automatic audit preservation.
- Anomaly-review tracking and source-aware cross-revision reporting (separate from ZIP acquisition and generated-content comparisons).

### Preview evidence and quality-control milestones - 16 November 2026

- **Individual GH audit and structural evidence:** Added read-only `/audit/history`, machine-level source findings including unpublished entries, and structural observations linked from Processing Diagnostics. Includes PORTS without category subheadings, near-miss banners, unidentified platforms and unmapped headings. Commits `408ec47`, `a7c5cab`, `5a4b690`.
- **GH Trivia suppression review:** Exposed removed source lines and exact suppression rules on game pages, plus aggregate removal and no-surviving-content counts. Commit `a700c63`. Real GH 2.89a evidence: 41,555 removed lines and 1,152 section records without surviving non-blank content. The latter may include originally empty sections.
- **Trivia classification and block provenance:** Committed an expandable per-game read-only block review and aggregate processing-policy figures, using existing `gh_system_trivia.json` metadata and `history_parsing_summary.json` (commit `e4e6784`; 29 focused tests passed at the implementation checkpoint). GH 2.89a classified 104,367 blocks: 63,383 paragraphs, 29,041 pairs, 4,436 subheadings, 4,296 bullet lists and 3,211 numbered lists.
- **Remaining GH structural evidence:** Exposed unusual PORTS categories and banner occurrences, plus recorded residue, on Diagnostics and relevant game pages (commit `bc2c410`; 30 focused tests passed). The 2.89a summary retained one unexpected category across five systems, 76 platform banners in eight systems and zero systems with recorded residue.
- **Publication deferral review:** Added machine-level reasons, search, filtering and pagination for raw PORTS-bearing parents excluded from Wiki publication (commit `a695fa4`; 25 focused tests passed). GH 2.89a retained reasons for all 64 deferred parents.
- **Transformation findings review:** Exposed individual title-anomaly records and affected parent/clone duplicate-PORTS machines; navigation conflict evidence is presented at the aggregate level retained by the summary (commit `ff51548`; 26 focused tests passed). GH 2.89a had zero title-anomaly records, nine duplicate-PORTS systems and 34 aggregate Wiki navigation conflicts.
- **Preview evidence-coverage close-out:** Audited recorded MAME, GH History, GH INI and Transformation summary findings against the Preview. MAME's rejected-display examples are bounded, and GH INI duplicate-assignment shortnames and individual Wiki navigation conflict details are not available in their stage summaries. No source detectors or pipeline behaviour were changed to manufacture evidence.
- **Heading review:** Comparison of local GH 2.81, 2.88 and 2.89a summaries found the same three occurrences across two rare non-standard names (`FORBIDDEN PLAYING METHODS`, `CAST OF ELEMENTS`). Their content remains preserved and no parser mapping change was made.
- **Boundary:** Preview diagnostics are read-only and independent of Wiki publishing. Source anomalies, structural observations, deliberately removed lines and block-processing statistics are different kinds of evidence; none is automatically a confirmed upstream defect.

### Added - November 2026

- **Gaming History revision acquisition and processing (14-15 November):** Read-only revision discovery, verified revised-ZIP downloads, canonical `historyNNN[a-z].zip` selection, and retention of original archives under the same four-digit release. Source selection remains separate from archive validation. Relevant commits: `dc367bd5`, `6f3da0ad`, `0ceb06d0`.
- **Safe GH revision provenance:** Guard selected History/INI processing against stale archive/member encoding metadata; refresh GH cache records using the existing detector while retaining unchanged MAME provenance. Stage-specific semantic encoding dependencies avoid needless MAME rebuilding. Relevant commits: `533c14d3`, `65eecbf4`, `02465416`.
- **Revision-specific History audit snapshots:** Preserve source-verified, immutable findings keyed by GH archive revision. Integrated automatic snapshot creation before the successful History stamp, and required snapshots for History freshness. Existing identical snapshots remain unchanged; conflicting ones are refused. Relevant commits: `bd447c80`, `b4a1e81`.
- **Read-only generated-content comparisons (12-13 November):** `mht diff` compares release Wiki output and GH Trivia, with combined machine impact, detailed Trivia diagnostics and Preview pages. This is a *content* comparison, not the planned revision-anomaly comparison. Relevant commits: `c807be95`, `72768a37`, `ba69021d`, `f859de01`, `d09d1ba6`.
- **History audit groundwork (10-12 November):** Persistent GH anomaly findings, additional PORTS checks for brackets/dates and audit/review utilities. These commits predate the revised-archive snapshot implementation; do not equate their cross-release audit work with the later snapshot-aware review workflow. Relevant commits: `91249be6`, `aead1090`, `22205033`, `f2439464`.
- **Selective stage execution and Preview improvements (November):** Central stage contracts, safer freshness reporting, targeted pipeline runs, structured Preview summaries and game navigation. Relevant commits: `393c1758`, `15c69125`, `67985196`, `b91b5258`.
- **Approved PS-SNAPS introductory wording (4 November):** Reviewed classifications, exact-key genre descriptions and generated LiT opening sentences. Relevant commits: `60a45c1d`, `feccac43`, `17aec888`.

### Changed - October-November 2026

- **Publication selection:** Canonical MAME parents with valid GH PORTS drive candidates, while Progetto-SNAPS CatList supplies category/genre information and publication eligibility following GH's discontinuation of `Machine Category.ini`. Relevant commits: `42ec7291`, `740ee22f`, `5c0f5b50`.
- **Acquisition provenance:** Added release-aware SNAPS acquisition, unified source acquisition records and historical manifest/audit commands. Relevant commits: `283093a7`, `6bad7626`, `98671a68`, `d232382e`.
- **Pipeline safeguards:** Better propagation of failures, refusal to use stale or missing upstream outputs and explicit output checks before treating stages as fresh. Relevant commits: `9ecf9436`, `71941ef8`, `bae15880`, `8941c8c5`.

### Added and changed - January-February 2026

- Refined the Preview structure, navigation and summaries; added ZIP-aware parsing-summary provenance and aligned transformation provenance and output counts. Relevant commits: `8488c1f9`, `0a03a55c`, `a3f4793d`, `ab5b57d1`, `f4b986b4`.

### Historical recovery note - 15 November 2026

- **Local data operation, not a repository feature commit:** The original GH 2.89 History audit was recovered from a checksum-verified pre-revision backup and matched to the retained `history289.zip` member's CRC32 and size. Both `history289.json` and `history289a.json` revision snapshots now exist locally. No History parsing rerun was required, and active outputs/stamps were not changed. Archive/snapshot data is not asserted to be tracked in Git.
- **Verification checkpoint:** After automatic snapshot integration, the user's Windows checkout reported 783 tests passed, one skipped; the 2.89a release had all four stages fresh. The live automatic-write path was covered by synthetic tests, not a forced production History rebuild.

### Documentation

- Added `PROJECT_STATUS.md` and `DESIGN_DECISIONS.md`, then refreshed them after automatic snapshot integration. `DEVELOPMENT_HANDOVER.md` remains local and ignored by Git.
- Older entries below remain preserved as historical release notes. No new semantic software version is claimed for the changes listed under Unreleased.

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
