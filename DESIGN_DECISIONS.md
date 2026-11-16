# MHT - Design Decisions

**Project:** MAME-History-Transformer (MHT)  
**Branch:** `v2`  
**Baseline:** 16 November 2026  
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
| DD-009 | Preserve revision-specific audit evidence immutably | Accepted, automatic History integration implemented |
| DD-010 | Separate upstream changes from detector changes | Planned comparison principle |
| DD-011 | Prefer additive compatibility and focused tests | Accepted practice |
| DD-012 | Keep conversation handovers separate from repository design records | Documentation convention |
| DD-013 | Retain historical GH Machine Category catalogue for optional research only | Accepted |
| DD-014 | Use reviewed PS-SNAPS gameplay descriptions as an independent exact-key lookup | Accepted vocabulary policy; implementation state to verify |
| DD-015 | Generate anomaly evidence automatically; preserve human review separately | Agreed design direction; detailed contract pending |
| DD-016 | Track GH upstream corrections separately from MAME workarounds and MHT defects | Agreed reporting principle; workflow pending |
| DD-017 | Keep generated Wiki content comparisons read-only and separate from anomaly-audit comparisons | Accepted and implemented for release content and Preview |
| DD-018 | Expose existing diagnostics and processing evidence without modifying parsers | Accepted; block-provenance increment awaiting commit |
| DD-019 | Preserve rare GH headings and distinguish aggregate statistics from actionable findings | Accepted |

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

**Important:** This is a deliberately settled architecture choice. Do not suggest synthesising a missing Machine Category INI as a routine workaround. The older GH category catalogue is optional research evidence, not an alternative mandatory classification input (see DD-013).

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

**Implementation:** `src/mht/provenance/gh_audit_snapshots.py` validates archive/audit provenance, embeds source audit content and SHA256s, then writes a revision-keyed JSON snapshot using exclusive file creation. Identical repeated saves are accepted; mismatched content is refused. The user reports successful manual creation of `history289a.json`. **Commit `b4a1e81`** integrated automatic preservation into `src/mht/inputs/history_xml_parser.py` after successful output generation and before saving the History stage stamp; `src/mht/utils/stage_contracts.py` requires the revision snapshot as a History output. The user reported 12 focused snapshot tests passing, 783 passed/1 skipped in the full suite, and a fresh History stage for 0289 after the change.

**Remaining boundary:** Existing older releases may lack the newly required snapshot. Historical recovery and compatibility are separate from implementing the automatic path; do not relabel a newer audit or trigger a destructive historical rebuild merely to satisfy freshness.

**Consequence:** Do not substitute an active 2.89a audit for a missing original 2.89 snapshot.

## DD-010 - Distinguish upstream fixes from detector changes

**Status:** Planned comparison principle, not implemented comparison capability.

**Decision intent:** When comparing revision snapshots, preserve detector versions and source provenance. Classify a missing finding as *potentially resolved* unless supported evidence establishes whether GH data changed, a detector changed, or a source became unprocessable.

**Rationale:** A finding disappearing after an MHT parser update is not equivalent to GH correcting the original text.

**Consequence:** Comparison reports need an indeterminate/requires-review category, not merely new/removed counts.

## DD-011 - Focused, additive development with regression checks

**Decision:** Prefer small source changes, stable output schemas and explicit tests. Preserve existing archives, release folders, unrelated untracked files and previous working outputs until new behaviour has passed controlled tests.

**Baseline:** The user reported **783 passed, 1 skipped** on 15 November 2026 after commit `b4a1e81` (earlier snapshot-utility checkpoint: 779 passed, 1 skipped). Tests ran in the user's checkout; these figures are historical checkpoints, not invariants.

**Practice:** Review the current source and tests, make an incremental patch, run focused tests, run full tests, inspect `git diff --check`, and stage explicit paths. Avoid `git add .` and broad cleanup commands.

## DD-012 - Documentation and conversational handovers

**Decision:** Keep `PROJECT_STATUS.md` and `DESIGN_DECISIONS.md` in the Git repository; keep `DEVELOPMENT_HANDOVER.md` as a local/conversation handover unless the user later opts to version it.

**Rationale:** Long-lived architecture and decisions belong beside code. A fast-changing conversational handover may contain transient information or assumptions that need not be part of the public repository.

**Maintenance:** Update the project status at milestones and the decision log when a real architectural choice changes. Refresh the separate handover before changing chat threads. The handover should point to source files and commit state rather than duplicate the full project history.

## DD-013 - Historical GH Machine Category catalogue is optional research data

**Decision:** Do not make the standalone historical GH classification catalogue a dependency of normal MHT parsing, transformation or publication. Retain the ability to consult or rebuild it for targeted investigations only.

**Background:** Earlier research assembled observations from archived GH INIs, approximately MAME releases `0271` to `0287`, before GH discontinued `Machine Category.ini`. The reported standalone JSON was approximately 45 MB and covered roughly 41,417 machines. These figures describe the historical research artefact, not a live requirement or a currently verified production dataset.

**Rationale:** Historical category values can explain past GH classifications and changes, but carrying them forward as authoritative classifications risks introducing stale evidence into newer releases. Current GH data, progetto-SNAPS and MAME metadata already support the selected production classification approach. The original archived releases are the reproducible source of any historical lookup.

**Implementation and scope:** `src/mht/utils/gh_category_history.py` supports historical category lookups and records the observed source release versus a carried-forward value. `src/mht/utils/classification_catalog.py` accepts an optional historical snapshot. Neither utility makes the catalogue mandatory. A carried-forward classification must remain distinguishable from one observed in the requested release.

**Distribution and maintenance:** Do not bundle or redistribute the aggregated catalogue by default; redistribution permission has not been established. Do not automatically synthesize a missing GH `Machine Category.ini`, override current SNAPS classifications, or change PORTS-based selection from this historical data. Keep the original archives available for reproducible research when needed.

**Revisit only if:** A concrete regression, reporting question or historical-comparison requirement cannot be addressed adequately from the current release sources. Establish the need and provenance before adding any new dependency.

## DD-014 - Reviewed PS-SNAPS genre vocabulary and source fidelity

**Decision:** Use the separately approved MAME 0.289 PS-SNAPS Arcade vocabulary, covering **134** Group / Category / Subcategory combinations relevant to LiT, as a complete-phrase lookup. Preserve the exact source classification key; the returned description already includes its initial indefinite article and `arcade video game` wording where applicable. Do not automatically add another article or suffix.

**Rationale:** The original classifications sometimes contain atypical or plainly misclassified games. The three-day audit evaluated the wider parent-game population for each category and selected a useful description of the dominant gameplay, rather than making the whole category vague because of exceptions. Avoid per-machine descriptions, automatic reclassification and silent source correction; any source problems remain independently documentable, with potential future wiki citations.

**Illustrative approved entries:**

| Original classification | Approved full introductory phrase |
| --- | --- |
| `Arcade / Fighter / Versus` | `a competitive fighting arcade video game` |
| `Arcade / Maze / Integrate` | `a repair-based action arcade video game` |
| `Arcade / Sports / Football` | `an American football arcade video game` |
| `Arcade / Sports / Soccer` | `a soccer-themed arcade video game` |
| `Arcade / Tabletop / Cards` | `a card-playing arcade video game` |
| `Arcade / MultiGame / Compilation` | `an arcade game compilation` |
| `Arcade / TTL * Ball & Paddle / Breakout` | `a target-clearing arcade video game` |
| `Arcade / TTL * Ball & Paddle / Pong` | `a table tennis arcade video game` |

The `TTL *` prefix is hardware-related and is retained in source lookup keys but does **not** dictate genre wording. Likewise `Ball & Paddle` is not a mandatory prose component. Distinct classification keys may intentionally share the same description. The approved vocabulary also distinguishes *American football* from *soccer*.

**Evidence and deliverable:** `lit_snaps_classification_review_0289_v96.xlsx`, especially the **Final approved lookup**, **Second-pass decisions** and **Final consistency audit** worksheets. The user reports creating a standalone JSON representation for another development thread; this record does not establish its filename, Git commit or runtime integration. Inspect the current repository before describing any of these as implemented. No production MHT code was changed during the vocabulary review itself.

**Separate future design questions:** A technology modifier for LaserDisc `interactive` or vector graphics is not part of the approved lookup policy. The existing `Arcade / Driving / Guide and Shoot` phrase is `an interactive driving action arcade video game`; `a reaction-based driving arcade video game` has been suggested but **not yet approved** as its replacement. Do not mutate the authoritative lookup until the project owner decides. Keep vocabulary integration independent of the immediate GH revision-audit work and add focused tests when integration is undertaken.

## DD-015 - Generated findings and independent human review

**Status:** Agreed design direction, not an implemented review workflow. The existing active History audit and automatically preserved revision snapshots are described in DD-009; persistent human review remains unimplemented.

**Decision intent:** MHT, not a manually assembled spreadsheet, should generate source-backed anomaly findings as part of its normal analysis. A spreadsheet or CSV may be *exported* for investigation, but should not become a competing authoritative detector output. Keep user review decisions separate from regenerated observations so a rerun or new GH revision cannot erase their history.

**Background:** The original MHT workflow exported detected anomalies to spreadsheets, followed by manual investigation and edits on the Gaming History website. The next GH version was expected to incorporate those edits and allow the reported cases to be checked again. Lettered GH revisions must participate in the same process.

**Proposed review information:** At minimum, preserve the anomaly rule and detector version; source family and archive/member identity; base release and GH revision; system, section, and source text; available original and filtered line provenance; and any supported proposed action. A distinct review record may later add a decision, status, rationale, date and upstream reference. Avoid treating unverified suggestions as automatic source corrections.

**Guardrails:** Reuse the existing `history_audit_findings.json`, `history_parsing_summary.json`, parser provenance and snapshot architecture. Do not introduce a manually maintained correction CSV as the primary system, silently edit GH input or make review metadata part of ExoticA's publication schema. Detailed identifiers, storage, export and UI contracts require further design and tests.

## DD-016 - Distinguish the responsibility and outcome of anomalies

**Status:** Agreed reporting principle; a unified classification and resolution workflow is not yet implemented.

**Decision intent:** Report findings according to their origin and appropriate action:

- **Gaming History source issue:** candidate for user review and upstream correction; verify whether later GH releases actually change the offending source.
- **MAME source incompatibility:** identify and document a local MHT workaround where needed, rather than assuming the user can submit a GH correction for MAME data.
- **MHT parsing or presentation issue:** address through code, fixtures and regression tests, not by falsely attributing it to GH or MAME.

**Rationale:** A finding disappearing can mean an upstream edit, a new local workaround, a changed detector, a removed record, or a source-processing failure. Such outcomes are not interchangeable.

**Consequence:** Future comparisons should distinguish new, persisting, changed and potentially resolved findings, with an indeterminate outcome when provenance or detector comparability is insufficient. Do not equate a clean audit with proof that every underlying issue was fixed. Review decisions and local workaround status must remain traceable across revisions and successive MAME releases.

**Example investigation (not a confirmed production detector):** A read-only audit of GH `0289` found 95 lines with a leading asterisk immediately followed by text. Of these, 35 Staff cases (32 emphasised pairs and three headings) were addressed by the Staff-specific parser change at `d613278`, with 636 tests passing at that earlier checkpoint. The other 60 cases require interpretation; `tumblep` demonstrated both list bullets and retained literal asterisks in the Preview. These historical counts are *not* the reported finding count for the newer GH `2.89a` audit. The lesson is to classify source conventions separately from confirmed upstream defects and presentation bugs.

## DD-017 - Generated Wiki content comparison is read-only and separate from anomaly audit

**Decision:** Compare publication-facing output from two completed MAME release directories using stable machine identifiers. Combine generated Wiki record changes with rendered GH Trivia changes, without double-counting affected machines. Report the affected *generated regions* rather than assuming an individual modified JSON field is an independent live Wiki edit.

**Rationale:** MAME and GH changes can affect multiple sections of the same LiT page. PORTS updates are section-level replacements; GH Trivia is independently generated and must not be overlooked merely because the Wiki JSON record is unchanged. A page name change, newly published record or withdrawn publication needs distinct treatment. The resulting count of affected machines is not necessarily the number of independent page operations on a live Wiki.

**Implementation:** `src/mht/audit/release_diff.py` compares generated Wiki data and page mappings; `trivia_diff.py` compares per-machine rendered sections; `combined_diff.py::compare_release_content()` merges the results. `trivia_details.py` uses Python's `difflib` to display changed paragraphs and structured blocks, suppressing unchanged content. `src/mht/cli.py` exposes `mht diff`, `--json`, `--details` and `--machine`. When versions are omitted, the CLI uses the active version and the numerically preceding available release. The feature and associated tests were committed before the 15 November 2026 documentation baseline.

**Trivia-specific boundary:** Compare generated section blocks (paragraphs, pairs, subheadings and list types) and disregard provenance/diagnostic metadata that does not alter the generated content. Do not assume the evolving `history.xml` parser yet recognises every formatting convention. MAME remains the preferred source of duplicated technical machine information; GH supplies PORTS and complementary Trivia. Accordingly, a GH Technical section's removal is a content difference, **not** proof of a parsing fault. For `twinhawk`, the original GH source actually removed the Technical section and referred readers to *Dai Senpuu*.

**Verified example, not a current invariant:** In the earlier 0.288 -> 0.289 processed outputs, the combined comparator reported 201 distinct affected machines (184 Wiki-related plus 22 with changed Trivia, five overlapping), including 17 Trivia-only machines and 35 changed Trivia sections. There were three page-name changes. The focused regression suite passed 39 tests. These values precede the later processing of GH 2.89a and must not be reused as a current revision-diff result.

**Separation from DD-009, DD-010, DD-015 and DD-016:** The working content comparison does **not** compare anomaly snapshots, determine whether an upstream GH typo was fixed, establish detector-version comparability or preserve human review decisions. Those are separate, unfinished anomaly-reporting responsibilities. The existing `mht diff` is read-only and does not modify source archives, regenerated datasets or the live ExoticA Wiki.

**Preview integration completed after this historical decision:** The existing Preview now offers `/compare` and `/compare/machine/<machine>` for read-only Wiki/Trivia output comparisons. This does not imply snapshot-aware anomaly comparison or persistent review decisions are complete. Preserve the original separation and reuse existing comparison functions.

## DD-018 - Preview diagnostics expose recorded evidence without modifying parser behaviour

**Status:** Accepted and implemented incrementally on `v2` (16 November 2026); block-provenance increment tested and visually reviewed but uncommitted at the documentation checkpoint.

**Decision:** Make MHT's existing source observations, structural diagnostics and deliberate filtering decisions readable in the local Preview. Preserve the difference between individual audit findings, structural observations, removal decisions, classification provenance and ordinary processing statistics. An unusual GH format or a suppression is not automatically a source error or MHT defect.

**Implementation:** `src/mht/preview/history_audit_review.py` shows individual GH source findings, including on unpublished systems; `history_structural_observations.py` displays retained summary observations with source excerpts or normalised labels as available; `history_suppression_review.py` presents recorded original removed lines and rules. `diagnostics.py` provides aggregate counts and safe links only for known Preview machines. `/summary/history` retains aggregate statistical context. New block review uses `history_block_review.py` and retained `gh_system_trivia.json` metadata (pending commit at this checkpoint).

**Evidence and distinctions:** GH 2.89a reported 41,555 removed lines, 1,152 section records with no surviving content and zero surviving blocks bearing suppression markers; these describe different stages of processing and are not contradictory. `wofch` and `kov7sprt` retain near-miss heading evidence even though the inspected rendered Trivia correctly shows subheadings. `sidearmsu` is an individual PORTS odd-quotes finding. Display limits must disclose omitted items, HTML escaping must protect source snippets, and diagnostics must not affect Wiki publication eligibility.

**Rationale:** The project owner wants to decide how to address detected problems later, using complete and attributable evidence, rather than allowing investigation of an interesting anomaly to trigger unplanned parser surgery. No parser changes, automatic GH corrections, new source dependencies or regeneration of release outputs are required to present information already retained.

## DD-019 - Preserve rare GH sections and distinguish statistics from actionable findings

**Status:** Accepted interpretation of the 16 November 2026 evidence; no new heading mapping approved.

**Decision:** Retain the two rare, unmapped GH section names as independent sections rather than forcibly assigning standard parents. Keep heading frequencies, block distributions and processing-policy invocation counts as statistics; promote a finding to a per-game review only when its recorded machine-level evidence supports that presentation.

**Evidence:** GH 2.89a has 10 recognised standard section headings, four explicit aliases and no observed mapped non-standard variants. `FORBIDDEN PLAYING METHODS` occurs for `hpolym84` and `hyprolym` and covers techniques that can invalidate scores; `CAST OF ELEMENTS` occurs for `missile` and describes gameplay objects. All three occurrences were also present in the compared 2.81 and 2.88 summaries. MHT already preserves and displays their sections. No semantic remapping follows from rarity alone.

**Consequences:** Continue the coverage audit of existing diagnostics. Do not treat aggregate block counts, heuristic policy invocations or suppression counts as machine-level anomalies. Record any future heading remapping as a separate, evidence-backed change with regression coverage, rather than burying it in a read-only Preview update.

## Updating decisions

When an existing decision is reconsidered, record the new evidence, exact affected modules and tests, user agreement and the date. If superseded, retain this historic entry with a reference to the replacement decision. Avoid rewriting the old rationale as if it never existed.
