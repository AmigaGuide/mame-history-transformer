# Roadmap (v2)

## Phase 1 — Structure & Contracts

* ✅ **Unified summary headers** across MAME/History/INI/Transform
  (`schema_id`, `schema_version=1.0.1`, `generated_at`, `versions`).

* ✅ **Centralised versions** in `src/mht/utils/versions.py`
  (schema IDs/versions, tool versions, output dataset schema IDs/versions).

* ✅ **Stage stamps/fingerprints** and “skip unchanged” execution

  * `inputs/history_parser.py` → `data/.stamps/history.json`
  * `inputs/mame_parser.py` → `data/.stamps/mame.json`
  * `transform/pipeline.py` → `data/.stamps/transform.json`
  * `inputs/history_ini_parser.py` → `data/.stamps/ini.json`
    Uses `stage_is_fresh / save_stamp` (wraps `make_stamp / load_stamp / is_fresh`).

* ✅ **Parser refactor to orchestrators**

  * **MAME:** event iterator, root-attr capture, helpers for chips/displays/controls/media/roms; invariants moved to `utils.validator`.
  * **History:** event iterator, root-attr capture, entry classification, sectioning and PORTS helpers; invariants moved to `utils.validator`.

* ✅ **Progress logging helper**
  `utils.logger.maybe_log_progress` used by both MAME and History.

* ⏳ **Docs: summary header spec** (add examples + legacy fallbacks).

* ◻ **Tiny validator tests (contracts)**

  * Headers present and match `versions.py`
  * Alias mirrors present where promised
  * Output schema IDs/versions (wiki/raw/pages) match `OUTPUT_SCHEMAS`

* ◻ **Gentle deprecation plan**
  Document legacy fields slated for removal and timelines.

---

## Phase 2 — CLI & Orchestration

* ✅ **`mht` CLI** with subcommands:

  * `run` – executes stages; incremental by stamps
  * `status` – shows stamp freshness for `mame/history/ini/transform`
  * `clean` – safe, confirm-by-default; `--dry-run` supported
  * `validate` – schema/contract checks

* ◻ **`status` extras**

  * Show which inputs changed (paths + mtimes/hash)
  * Highlight tool/schema bumps that invalidate stamps
  * Suggest next actions

---

## Phase 3 — Validation & Invariants

* ◻ **Schema validation & invariants**

  * Parents + clones totals, display/device counters add up
  * Unique redirects; conflicts surfaced
  * Provenance completeness for GH ports (parent/clone sources)

* ◻ **Performance guardrails**

  * Parse/transform wall-clock budgets (warn on regressions)
  * Memory thresholds on large inputs (warn)

* ◻ **Contract tests**

  * Assert wiki/raw/pages schema IDs/versions match `OUTPUT_SCHEMAS`
  * Header-first version reads succeed with legacy fallbacks

---

## Phase 4 — Nice-to-haves

* ◻ **Optional YAML renderer** for human diffing of key artefacts.
* ◻ **Read-only mini viewer** for summaries/artefacts (local HTML).
* ◻ **(Future) GH TRIVIA parsing** as its own stage feeding transform.
* ◻ **Whitelist toggle** for known benign anomalies (e.g., `bitmap_printer`) while preserving audit trails.

---

## Phase 1 Wrap-Up Checklist

* [ ] Bump patch versions of `mame_parser`, `history_parser`, `transformer` (pipeline), and `ini_summary`.
* [ ] End-to-end run on full inputs; confirm stamps skip re-runs.
* [ ] Review `data/*_parsing_summary.json` & `data/transform_summary.json` warnings.
* [ ] Decide policy on committing large `output/` artefacts vs. `.gitignore`.
* [ ] README refresh committed (module map + stamps helper usage).
* [ ] ROADMAP updated (this file).
