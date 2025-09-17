# Roadmap (v2)

## Phase 1 — Structure & Contracts
- Introduce JSON Schemas for each artefact; embed `schema_version` in outputs.
- Add stage stamps/fingerprints and skip unchanged work.
- Split transformer into focused modules (titles, ROM/media, displays, controls, chips, ports, redirects).

## Phase 2 — CLI & Orchestration
- `mht` CLI with subcommands: `status`, `parse`, `select`, `join`, `transform`, `validate`, `run`, `clean`.
- `status` shows stale/up-to-date by stage with reasons.
- `run` executes only stale stages by default.

## Phase 3 — Validation & Invariants
- Schema validation and invariant checks (parents+clones totals, unique redirects, provenance completeness).
- Performance guardrails (warn on regressions).

## Phase 4 — Nice-to-haves
- Optional YAML renderer.
- Small read-only viewer for artefacts.
- (Future) GH TRIVIA parsing as a separate stage.

