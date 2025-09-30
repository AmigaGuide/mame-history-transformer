# Roadmap (v2)

## Phase 1 — Structure & Contracts

* ✅ **Unified summary headers** across MAME/History/INI/Transform  
  (`schema_id`, `schema_version=1.0.1`, `generated_at`, `versions`).

* ✅ **Centralised versions** in `src/mht/utils/versions.py`  
  (schema IDs/versions, tool versions, output dataset schema IDs/versions).

* ✅ **Stage stamps/fingerprints** and “skip unchanged” execution  
  - `history_parser.py` → `data/.stamps/history.json`  
  - `mame_parser.py` → `data/.stamps/mame.json`  
  - `transformer.py` → `data/.stamps/transform.json`  
  Uses `make_stamp / load_stamp / is_fresh / save_stamp`.

* ⏳ **Docs: summary header spec** (add examples + legacy fallbacks).

* ◻ **Tiny validator tests (contracts)**  
  - Headers present and match `versions.py`  
  - Alias mirrors present where promised  
  - Output schema IDs/versions (wiki/raw/pages) match `OUTPUT_SCHEMAS`

* ◻ **Gentle deprecation plan**  
  Document legacy fields slated for removal and timelines.

---

## Phase 2 — CLI & Orchestration

* ◻ **`mht` CLI** with subcommands:
  - `status` – show stale/up-to-date per stage with reasons (stamp diff)
  - `parse` – run individual parsers (`mame|history|ini`)
  - `select` – (reserved for future filtering step)
  - `join` – (reserved; GH↔MAME enrichment point)
  - `transform` – run transformer only
  - `validate` – run schema/contract checks
  - `run` – execute only stale stages (default); `--all` to force
  - `clean` – remove generated artefacts and stamps

* ◻ **`status`** displays:
  - Inputs that changed (paths + mtimes/hash)
  - Tool version or schema bumps that invalidate stamps
  - Next actions (`run` suggestions)

* ◻ **`run` default = incremental**  
  Executes stages in dependency order, skipping fresh ones via stamps.

---

## Phase 3 — Validation & Invariants

* ◻ **Schema validation & invariants**
  - Parents + clones totals, display/device counters add up
  - Unique redirects; conflicts surfaced
  - Provenance completeness for GH ports (parent/clone sources)

* ◻ **Performance guardrails**
  - Parse/transform wall-clock budgets (warn on regressions)
  - Memory thresholds on large inputs (warn)

* ◻ **Contract tests**
  - Assert wiki/raw/pages schema IDs/versions match `OUTPUT_SCHEMAS`
  - Header-first version reads succeed with legacy fallbacks

---

## Phase 4 — Nice-to-haves

* ◻ **Optional YAML renderer** for human diffing of key artefacts.
* ◻ **Read-only mini viewer** for summaries/artefacts (local HTML).
* ◻ **(Future) GH TRIVIA parsing** as its own stage feeding transform.
* ◻ **Whitelist toggle** for known benign anomalies (e.g., `bitmap_printer`)
  while preserving audit trails.

---

## Phase 1 Wrap-Up Checklist

- [ ] Bump patch versions of `history_parser.py`, `mame_parser.py`, `transformer.py`.
- [ ] End-to-end run on full inputs; confirm stamps skip re-runs.
- [ ] Review `data/*_parsing_summary.json` & `data/transform_summary.json` warnings.
- [ ] Decide policy on committing large `output/` artefacts vs. `.gitignore`.
