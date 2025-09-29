# Changelog

All notable changes to this project will be documented here.

## [Unreleased]
- CLI flags for `qa.py` (e.g. --no-tests)
- Centralise data-source versions (optional) and minor header utilities
- Plan removal of legacy summary fields in a future major release

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
