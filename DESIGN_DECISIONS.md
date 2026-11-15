# MHT - Design Decisions

**Project:** MAME-History-Transformer (MHT)  
**Branch:** `v2`  
**Baseline:** 15 November 2026  
**Purpose:** Record settled design intent and rationale, not just the latest implementation details.

> When changing existing behaviour, inspect the referenced modules and tests first. These records document decisions understood from the current code and project discussions. They are not a substitute for source code. If a decision must change, mark the old entry superseded and explain the replacement rather than silently rewriting history.

## Decision index

| ID | Decision | Status |
| --- | --- | --- |
| DD-001 | Use a base MAME release with lettered GH revisions | Accepted |
| DD-002 | Retain all verified GH revision archives | Accepted |
| DD-003 | Use one authoritative per-release encoding cache | Accepted |
| DD-004 | Make encoding freshness stage-specific | Accepted |
| DD-005 | Treat source-provenance mismatches as blockers | Accepted |
| DD-006 | Use SNAPS after GH Machine Category INI was discontinued | Accepted |
| DD-007 | Preserve GH PORTS independently of legacy arcade eligibility | Accepted |
| DD-008 | Preserve genuine source anomalies for manual correction | Accepted |
| DD-009 | Preserve revision-specific audit evidence immutably | Accepted, manual operation implemented |
| DD-010 | Separate upstream changes from detector changes | Planned comparison principle |
| DD-011 | Prefer additive compatibility and focused tests | Accepted practice |
| DD-012 | Keep conversation handovers separate from repository design records | Documentation convention |

## DD-001 - Base release and GH revision model

**Decision:** Use the four-digit MAME release key, such as `0289`, as the unit of MHT release storage. Support canonical GH ZIP names `history289.zip`, `history289a.zip`, `history289b.zip`, etc. within that folder.

**Rationale:** GH may revise metadata independently of the underlying MAME version. Revision suffixes are source-specific, not new MAME releases.

**Current implementation:** `src/mht/provenance/gh_archive_selection.py::select_history_archive()` selects the highest staged revision and rejects ambiguous case-insensitive duplicates. Ingest and provenance verification are separate from filename selection.

**Consequence:** Do not create `0289a` release folders or replace the original `history289.zip` simply because a revision exists.

## DD-002 - Preserve verified original and revised archives

**Decision:** Keep previously staged GH archive revisions available for provenance, reconstruction and comparison.

**Rationale:** Historical source archives help establish which changes originated upstream and support audit comparisons without guessing from the newest release alone.

**Current evidence:** User retained `history289.zip` when ingesting `history289a.zip` and made a pre-revision backup.

**Caution:** Archive retention does not by itself mean historic generated findings have been preserved; those require their own verified audit snapshots.

## DD-003 - One per-release encoding cache

**Decision:** Retain `data/releases/<ver>/encodings.json` as the authoritative encoding and member-provenance cache.

**Rationale:** Multiple parallel caches would increase synchronisation complexity and create competing metadata sources.

**Implementation:** `src/mht/utils/encoding_utils.py` handles detection/cache operations. `src/mht/utils/gh_encoding_refresh.py` reuses its existing detector and validates proposed GH changes before replacing the cache.

**Consequence:** Do not introduce stage-specific encoding JSON sidecars merely to solve stamp freshness.

## DD-004 - Stage-specific encoding freshness

**Decision:** Track only the encoding records actually relevant to the current parsing stage.

**Rationale:** Refreshing GH entries should not make MAME stale when its source and encoding have not changed.

**Implementation:** `src/mht/utils/encoding_stamp.py`, `stamps.py`, `stage_contracts.py`; includes conservative compatibility for legacy stamps. The actual GH 2.89a processing retained a fresh MAME stage while both GH stages were rebuilt.

**Consequence:** Do not regress to digesting the full cache's modification time as an independent dependency for every stage.

## DD-005 - Explicit encoding/source provenance checks

**Decision:** Refuse parsing with cached encoding entries referring to superseded ZIP archives or mismatched members.

**Rationale:** Even if two versions use UTF-8, the cache must correctly identify the member that was inspected. Silent fallback can hide data-integrity faults.

**Implementation:** Read-only `gh_encoding_guard.py` checks the archive name, member path, CRC32, size and encoding presence. `gh_encoding_refresh.py` proposes new records, verifies the unchanged MAME record, validates GH History and INI entries, then writes the cache.

**Failure expectation:** No parser execution or forced stamp deletion after failed preflight. Test with isolated fixtures and temporary cache paths before changing release files.

## DD-006 - SNAPS classification after GH removed Machine Category INI

**Decision:** Use Progetto-SNAPS CatList classification as the replacement source for appropriate genre/category publication logic. GH `Machine Category.ini` is optional and may be absent without constituting an error.

**Rationale:** GH discontinued that INI. Earlier reliance on its category values could no longer provide complete classification.

**Implementation:** `src/mht/utils/snaps.py` and transformer. SNAPS classifications are loaded from a release `ps_*.zip` containing a unique CatList member.

**Important:** This is a deliberately settled architecture choice. Do not suggest synthesising a missing Machine Category INI as a routine workaround.

## DD-007 - PORTS-based parent selection

**Decision:** Select canonical MAME parents with valid GH PORTS, including when PORTS are attached only to a clone. Keep legacy INI arcade eligibility as diagnostic information rather than the selection gate.

**Rationale:** The project serves LiT's arcade-to-home-port content, which must not disappear because an older GH INI classification was removed.

**Implementation:** `src/mht/utils/selection.py::build_ports_parent_set()` and `src/mht/transform/pipeline.py`. SNAPS-based approval controls publication after selection.

**Observed result:** The GH 2.89a transformer logged zero `Arcade-eligible parents` but selected 1,628 parent candidates and published 1,564. The zero diagnostic must not automatically be treated as a selection failure.

## DD-008 - Report genuine source anomalies, do not hide them

**Decision:** Anomaly detectors should identify questionable upstream GH text for manual investigation. Do not add machine-specific exceptions merely to silence expected findings.

**Example:** `sidearmsu`, PORTS text:

```text
[US] PC [MS-DOS, 3.25"] (1991) "Arcade Hits"
```

The existing quote detector recognises valid disk-size quoting (e.g. `3.5"`, `5.25"`). The user has confirmed the `3.25"` text is a typo in this specific entry and that the detector correctly reports it. A separate fact that some obscure disk formats used 3.25-inch media does not make this particular source text correct.

**Consequence:** Review or correct upstream data manually where appropriate; do not automatically rewrite original GH records or suppress correct findings.

## DD-009 - Immutable, revision-specific anomaly evidence

**Decision:** Preserve independent audit findings and source fingerprints for each processed GH ZIP revision, while keeping `history_audit_findings.json` as the current release's active audit.

**Rationale:** The active audit is regenerated when History runs. Revision comparisons require trustworthy earlier evidence.

**Implementation today:** `src/mht/provenance/gh_audit_snapshots.py` validates archive/audit provenance, embeds source audit content and SHA256s, then writes a revision-keyed JSON snapshot using exclusive file creation. Identical repeated saves are accepted; mismatched content is refused. The user reports successful creation of `history289a.json`.

**Next:** Integrate automatic preservation into successful History processing. This integration is **not yet implemented** at this baseline.

**Consequence:** Do not substitute an active 2.89a audit for a missing original 2.89 snapshot.

## DD-010 - Distinguish upstream fixes from detector changes

**Status:** Planned comparison principle, not implemented comparison capability.

**Decision intent:** When comparing revision snapshots, preserve detector versions and source provenance. Classify a missing finding as *potentially resolved* unless supported evidence establishes whether GH data changed, a detector changed, or a source became unprocessable.

**Rationale:** A finding disappearing after an MHT parser update is not equivalent to GH correcting the original text.

**Consequence:** Comparison reports need an indeterminate/requires-review category, not merely new/removed counts.

## DD-011 - Focused, additive development with regression checks

**Decision:** Prefer small source changes, stable output schemas and explicit tests. Preserve existing archives, release folders, unrelated untracked files and previous working outputs until new behaviour has passed controlled tests.

**Baseline:** The user reported **779 passed, 1 skipped** on 15 November 2026. Tests run in the user's checkout; this figure is not an invariant.

**Practice:** Review the current source and tests, make an incremental patch, run focused tests, run full tests, inspect `git diff --check`, and stage explicit paths. Avoid `git add .` and broad cleanup commands.

## DD-012 - Documentation and conversational handovers

**Decision:** Keep `PROJECT_STATUS.md` and `DESIGN_DECISIONS.md` in the Git repository; keep `DEVELOPMENT_HANDOVER.md` as a local/conversation handover unless the user later opts to version it.

**Rationale:** Long-lived architecture and decisions belong beside code. A fast-changing conversational handover may contain transient information or assumptions that need not be part of the public repository.

**Maintenance:** Update the project status at milestones and the decision log when a real architectural choice changes. Refresh the separate handover before changing chat threads. The handover should point to source files and commit state rather than duplicate the full project history.

## Updating decisions

When an existing decision is reconsidered, record the new evidence, exact affected modules and tests, user agreement and the date. If superseded, retain this historic entry with a reference to the replacement decision. Avoid rewriting the old rationale as if it never existed.
