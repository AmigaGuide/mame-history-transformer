# Roadmap (v2)

## Phase 1 — Structure & Contracts

* ✅ **Unified summary headers** across MAME/History/INI/Transform (`schema_id`, `schema_version=1.0.1`, `generated_at`, `versions`).
* ✅ **Centralised versions** in `src/mht/versions.py` (schema IDs/versions, tool versions, output dataset schema IDs/versions).
* ✅ **Transformer reads versions header-first** with legacy fallbacks; no more `null` in transform summary.
* ◻ **Stage stamps/fingerprints** and “skip unchanged” execution.
* ◻ **Split transformer into focused modules** (titles, ROM/media, displays, controls, chips, ports, redirects).
* ◻ **Tiny validator tests** to lock the contract (header presence, alias mirrors, output schema IDs/versions match `versions.py`).
* ◻ **README/Docs**: summary header section (added), keep refining as modules split.
* ◻ **Gentle deprecation plan**: retire legacy fields in a future major version (document timelines).

## Phase 2 — CLI & Orchestration

* ◻ `mht` CLI with subcommands: `status`, `parse`, `select`, `join`, `transform`, `validate`, `run`, `clean`.
* ◻ `status` shows stale/up-to-date by stage with reasons.
* ◻ `run` executes only stale stages by default.

## Phase 3 — Validation & Invariants

* ◻ Schema validation and invariant checks (parents+clones totals, unique redirects, provenance completeness).
* ◻ Performance guardrails (warn on regressions).
* ◻ Tests asserting output dataset schema IDs/versions (wiki/raw/pages) match `OUTPUT_SCHEMAS`.

## Phase 4 — Nice-to-haves

* ◻ Optional YAML renderer.
* ◻ Small read-only viewer for artefacts.
* ◻ (Future) GH TRIVIA parsing as a separate stage.
* ◻ Whitelist toggle for known benign anomalies (e.g. `bitmap_printer`) without losing audit trail.
