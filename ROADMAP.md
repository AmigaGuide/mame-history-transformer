# Roadmap (v2)

## Phase 1 — Structure & Contracts (complete)

✅ **Unified summary headers**
All stages now share a standard header (`schema_id`, `schema_version`, `generated_at`, `versions`).

✅ **Centralised versions** in `mht/utils/versions.py`
(Schema IDs/versions, tool versions, and output dataset schemas.)

✅ **Per-release provenance**
Each release maintains its own:

* `archives/` (ZIPs)
* `.stamps/` (stage fingerprints)
* `encodings.json` (encoding + version cache)

✅ **Parser refactor to orchestrators**
`mame_parser.py`, `history_xml_parser.py`, and `history_ini_parser.py` now delegate to helpers under `utils/`.

✅ **ZIP-only pipeline**
All inputs are read directly from archives; extraction removed.

✅ **Progress & logging helpers**
`utils.logger.maybe_log_progress()` and `debug_log()` unify output; optional `--debug` for network probes.

✅ **Docs & tests**
README, CHANGELOG, and test suite updated; pytest fully green across Windows paths.

---

## Phase 2 — CLI & Orchestration (stable)

✅ **`mht` CLI core**

* `run` — explicit full pipeline (no longer default).
* `status` — stamp freshness summary.
* `clean` — safe cleanup with `--dry-run`/`--yes`.
* `validate` — schema validation for outputs.
* `fetch` — probe and download upstream MAME + GH ZIPs.
* `ingest` — auto-route incoming ZIPs by version hint/build.
* `releases` — manage active version, index, prune, GC.
* `incoming` — inspect or adopt staged archives.

✅ **User experience**

* Root (`python -m mht`) prints help + active release (no automatic run).
* Parent groups print contextual help instead of argparse errors.
* All commands show `[active] release = <ver>` banner (root excluded).

✅ **Fetch debugging**

* `--debug` logs every attempted online URL (`history282.zip`, `history282a.zip`, …).
* Duplicate downloads skipped unless `--overwrite` given.

✅ **Releases index**

* `releases_index.json` summarises archives, outputs, summaries, encodings per release.
* All paths normalised via `as_posix()` for cross-platform stability.

⏳ **Next CLI tasks**

* Add `mht diff` to compare outputs or summaries between two releases.
* Optional `--json` output for `status` (machine-readable CI use).

---

## Phase 3 — Validation & Invariants (in progress)

◻ **Schema + invariant tests**

* Verify parent/clone counts, display/device totals.
* Ensure unique redirects and provenance completeness (PORTS).
* Confirm output dataset schemas match `OUTPUT_SCHEMAS`.

◻ **Performance guardrails**

* Record wall-clock and memory metrics per stage; warn on regressions.

◻ **Contract tests**

* Header-first version reads (with fallbacks) validated automatically.
* Confirm every stage writes a valid stamp and summary header.

---

## Phase 4 — Nice-to-haves (planned)

◻ **Optional YAML renderer** for key artefacts (human-diff friendly).
◻ **Read-only HTML viewer** for summaries and run manifests.
◻ **GH TRIVIA parsing** as a future optional stage feeding transform.
◻ **Whitelist toggle** for benign anomalies (e.g. `bitmap_printer`) while keeping audit trail.
◻ **Release diff engine** – compare `mame_machines.json` or `gh_system_ports.json` across versions.

---

## Maintenance Checklist (before v1.1.0 tag)

* [x] Update `README.md` and `CHANGELOG.md`.
* [x] Confirm all CLI help screens and banners consistent.
* [x] End-to-end parse on 0.281 data set with correct per-release stamps.
* [x] Full `pytest` suite passes (Windows paths included).
* [ ] Run `pyflakes`/`ruff` to remove any unused imports or variables.
* [ ] Tag release `v1.1.0` and rebuild `releases_index.json`.

