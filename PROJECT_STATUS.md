# MHT - Project Status

**Project:** MAME-History-Transformer (MHT)  
**Repository:** `AmigaGuide/mame-history-transformer`  
**Development branch:** `v2`  
**Baseline date:** 15 November 2026  
**Status:** Core GH ZIP revision implementation complete; historical recovery verified; anomaly comparison is a separate workstream  
**Companion:** `DESIGN_DECISIONS.md`

> **Read this first when resuming development.** This document records the verified v2 architecture, known operational state and unfinished work. Source code and passing tests are authoritative for executable behaviour. Decisions are explained separately in `DESIGN_DECISIONS.md`. Update the current position after each substantial development increment, and distinguish verified facts from intentions.

## 1. Current development position

### Latest confirmed results

- The user reports a full regression suite of **783 passed, 1 skipped** (15 November 2026) after integrating automatic GH audit snapshot preservation; the 12 focused snapshot tests passed. These results come from the user's Windows checkout, not from a new test run during this documentation update.
- The user reports `python -m mht status --version 0289` showing **INI, MAME, History and Transform all fresh** after processing `history289a.zip`.
- The selected GH revision is `history289a.zip`; the original `history289.zip` is retained in the same release archives directory.
- The revised History XML declares **2.89a**, dated **2026-11-09**. The archive's History, Game Or No Game and Machine Type members have been verified against their ZIP CRC32 values.
- MAME parsing was **not** repeated for this GH revision. Its provenance stayed unchanged and its stage remained fresh.
- An immutable audit snapshot was created at `data/releases/0289/summaries/gh_audit_revisions/history289a.json` using the standalone command before integration. The subsequent automatic implementation recognises that snapshot without replacing it.
- The user subsequently verified `data/backups/0289-before-history289a.zip` (SHA256 `3326fa6d514f50a8e0247cd7994753132931e25d91ef2b6a21dadc35e26a651e`) and recovered the **original 2.89** audit to `gh_audit_revisions/history289.json`. Its `history/history.xml` member was verified against the original `history289.zip` (CRC32 `F70F6180`, 64,217,187 bytes). The original audit contained one finding and declared GH 2.89 dated 2026-08-07. Neither the active audit nor the outputs, cache or stage stamps were modified.
- **Automatic GH audit snapshot preservation is implemented and committed** in `b4a1e81`. The History parser preserves the selected revision's audit after successfully writing its outputs and before saving its stage stamp. The History stage contract requires the revision-specific snapshot for freshness. The user verified all four stages remained fresh afterwards. No new full History parse was performed to exercise the automatic path on the real 2.89a dataset.
- Separately, the user confirmed that the generated Wiki release comparison, combined Trivia comparison and detailed Trivia diagnostics were committed to `v2` before this baseline. The focused regression run at that earlier checkpoint passed **39 tests**. The reported GH 2.89a processing and **783 passed, 1 skipped** full-suite checkpoint are more recent; do not substitute the older 0.288-to-0.289 content-diff counts for a fresh comparison of GH 2.89a outputs.

### Anomaly-reporting handover note

The intended deliverable is automatic, source-backed findings plus a separate, persistent manual review history; a manually maintained CSV is not the primary record. Source responsibility matters: GH findings may be corrected upstream, MAME irregularities generally require documented local workarounds, and MHT interpretation defects require parser or rendering changes. Compare original and lettered GH revisions without assuming that a vanished finding proves an upstream correction. These are design requirements, **not** a claim that the review workflow or cross-revision comparator already exists. See DD-009, DD-010, DD-015 and DD-016.

### Current ZIP revision workstream status

**Core implementation complete.** Revision discovery, verified acquisition, source selection, provenance refresh, selective rebuilds and automatic audit snapshots have passed tests and been exercised against GH 2.89a where applicable. The local 2.89 backup inspection and recovery described below are complete. Remaining historical-snapshot compatibility and additional real-world suffix coverage are optional hardening, not blockers for declaring the core ZIP revision work complete.

**Next documentation task:** bring the previously stale `CHANGELOG.md` up to date from commit history, without assigning an unissued release version. Cross-revision anomaly analysis is a separate workstream and must not be introduced as a ZIP-revision prerequisite.

### Latest stage outcome, GH 2.89a

| Stage | Reported status | Notable result |
| --- | --- | --- |
| MAME | Fresh | Cached MAME metadata reused; no parser rerun |
| INI | Fresh | Both available INIs list 41,703 unique names; Machine Category INI absent |
| History | Fresh | 117,014 entries: 18,578 systems, 98,436 software |
| Transform | Fresh | 1,628 parent records, 1,564 publishable, 64 deferred |

Additional figures from the user's logs: 18,363 systems with trivia output; 203 entries with port overviews; one History audit observation; 50,368 SNAPS classifications loaded by the transformer; 3.46 seconds for transformation. These numbers describe this particular release and run, not permanent invariants.

## 2. Project purpose and history

MHT transforms MAME and Gaming History source metadata into structured, documented, ExoticA-ready outputs for the Lost in Translation (LiT) wiki. It originated in the Open University TM470 project *Adapting MAME and Gaming-History XML Metadata for ExoticA's Lost in Translation*. The README identifies the EMA snapshot on `main` with tags `tm470-ema-2025` and `v1.0.0`; active work is on `v2`.

v2 is a modular Python application. It favours direct ZIP reading, per-release processing, provenance, consistent output schemas, stage freshness checks and regression tests. It also includes a local preview interface and anomaly diagnostics. The current project priority is GH revision handling and longitudinal anomaly reporting, not reworking the original TM470 submission.

## 3. Repository and runtime entry points

| Path | Responsibility |
| --- | --- |
| `src/mht/__main__.py`, `src/mht/cli.py` | CLI entry point and command dispatch |
| `main.py` | Full pipeline orchestration, including encoding detection and run manifest |
| `src/mht/selected_run.py` | One-stage execution, input checks, GH refresh and upstream guard |
| `src/mht/inputs/mame_parser.py` | MAME XML parsing and MAME outputs |
| `src/mht/inputs/history_ini_parser.py` | GH INI parsing and classification output |
| `src/mht/inputs/history_xml_parser.py` | GH XML, PORTS, trivia and audit findings |
| `src/mht/transform/pipeline.py` | Joins source data, selects parents and creates ExoticA outputs |
| `src/mht/utils/snaps.py` | Progetto-SNAPS CatList and publication-related classifications |
| `src/mht/utils/stage_contracts.py` | Canonical inputs/outputs for four stage contracts |
| `src/mht/utils/stamps.py`, `encoding_stamp.py` | Stamp digests and stage-specific encoding signatures |
| `src/mht/utils/gh_encoding_guard.py` | Read-only source/member encoding provenance verification |
| `src/mht/utils/gh_encoding_refresh.py` | Validated GH cache refresh using the existing detector |
| `src/mht/utils/encoding_utils.py` | ZIP-aware encoding detection and cache persistence |
| `src/mht/provenance/gh_archive_selection.py` | Authoritative revision ZIP selection |
| `src/mht/provenance/gh_audit_snapshots.py` | Source-verified immutable audit snapshots, standalone command and automatic History integration |
| `src/mht/audit/release_diff.py` | Compare generated Wiki records and affected regions across release folders |
| `src/mht/audit/trivia_diff.py` | Compare rendered GH Trivia sections, excluding diagnostic metadata |
| `src/mht/audit/combined_diff.py` | Combine Wiki and Trivia impact without double-counting machines |
| `src/mht/audit/trivia_details.py` | Human-readable changed-block diagnostics using `difflib` |
| `src/mht/preview/` | Existing local Preview interface; diff integration is a separate future task |
| `src/mht/utils/paths.py` | Release-aware path helpers and compatibility aliases |
| `src/mht/utils/versions.py` | Tool versions and schema identifiers |
| `tests/` | Automated regression tests |

This map is an overview, not a complete module inventory. Inspect actual imports and tests before changing any subsystem.

### Standard workflow commands

```bash
python -m pytest -q
python -m mht status --version 0289
python -m mht run --only ini
python -m mht run --only history
python -m mht run --only transform
python -m mht.provenance.gh_audit_snapshots --version 0289 --archive history289a.zip
python -m mht diff 0288 0289
python -m mht diff --machine xevious
python -m mht diff --details
python -m mht diff --json
```

The selected run uses the active release. `--version` in the examples above is for status and snapshot operations, not evidence that the `run --only` command accepts a version argument. Do not run parsing commands on historical releases without a confirmed backup or an intentionally isolated dataset.

## 4. Per-release data layout

```text
data/
  incoming/
  releases/
    0289/
      archives/
        mame0289lx.zip
        history289.zip
        history289a.zip
        ps_*.zip                 # SNAPS archive, exact name varies
      encodings.json
      outputs/
        mame_machines.json
        mame_parent_index.json
        gh_ini_classifications.json
        gh_system_ports.json
        gh_system_trivia.json
        exotica_lit_raw_data.json
        exotica_lit_wiki.json
        exotica_wiki_pages_and_redirects.json
      summaries/
        mame_parsing_summary.json
        ini_parsing_summary.json
        history_parsing_summary.json
        history_audit_findings.json
        transform_summary.json
        gh_audit_revisions/
          history289a.json
      .stamps/
        ini.json
        mame.json
        history.json
        transform.json
```

The sample is illustrative; `ps_*.zip` is a naming pattern, not a literal filename. The structure may also contain manifest, preview, auxiliary or historical files. Never delete files because they are absent from this summary.

## 5. Processing architecture and freshness

MHT has four recognised stages: `ini`, `mame`, `history`, and `transform`.

- **MAME:** source MAME archive (or supported XML fallback) plus only its relevant encoding metadata. Produces canonical machine records, parent/clone index and summary.
- **INI:** selected GH ZIP plus Game Or No Game, Machine Category (optional) and Machine Type encoding records. Produces classifications and summary.
- **History:** selected GH ZIP plus History XML encoding record. Produces structured systems/PORTS, trivia, summary and audit findings.
- **Transform:** reads upstream outputs and relevant lookups/SNAPS classifications to produce ExoticA outputs and transform summary. Selected transform execution refuses stale upstream stages.

`stage_contracts.py` centralises the stage contracts. `stage_is_fresh` checks digests and required outputs, and `encoding_stamp.py` calculates **stage-specific semantic encoding dependencies**. A change to GH encoding metadata alone must not invalidate the MAME stage. Conservative compatibility checking supports older stage stamps where source and cached provenance agree. Do not replace these checks with a modification-time dependency on the whole encoding cache.

### Encoding cache behaviour

There is **one** authoritative per-release `encodings.json`. It contains encoding and ZIP member provenance (archive, member, CRC32, uncompressed size). The GH guard rejects mismatches. The GH refresh helper uses the existing `detect_encodings_from_archives()` detector, verifies unchanged MAME metadata and validates both GH XML and INIs before saving. The helper can accept an explicit cache path for isolated testing. A failed validation must not start a selected parser or remove the stage stamp.

### GH revision selection

The selector accepts canonical `historyNNN.zip`, `historyNNNa.zip` through `historyNNNz.zip` filename patterns for a four-digit MHT release key. The base ZIP is revision zero; the latest valid staged suffix is chosen. Case-insensitive duplicate revision names are rejected. Selection by filename is **not** the same as archive verification: ingest and provenance checks are separate responsibilities. Different revisions belong under the same base release folder, e.g. `0289`; do not create `0289a` as a release directory.

## 6. Source material and classification

### MAME

MAME XML supplies machine identity, parent/clone relationships, hardware, controls, displays and other structured metadata. Parsing and transform behaviour are intentionally separate. MAME-source limitations are handled locally where necessary and documented rather than assuming upstream GH can fix MAME data.

### Gaming History

GH History XML contains relevant PORTS information and trivia. GH INIs can provide game/no-game status and machine type. Some newer GH archives omit `[GAMING HISTORY] Machine Category.ini`, which is **expected**. The absence is not a parser regression and should not lead to inventing an INI.

### Historical GH Machine Category catalogue - research only

Earlier research assembled a standalone catalogue of historical GH INI observations, approximately releases `0271` to `0287`, before the Machine Category INI was discontinued. The reported JSON was about **45 MB** with classifications for approximately **41,417 machines**. These are historical research figures, not measurements from the current `0289` run.

**Settled decision (DD-013):** The catalogue is **not required by the production pipeline**, is not a replacement for current SNAPS classification, and must not be used to fabricate missing GH INIs or determine PORTS eligibility. `src/mht/utils/gh_category_history.py` and `src/mht/utils/classification_catalog.py` support optional, provenance-aware historical lookups. The catalogue can be reconstructed from archived GH releases if a specific investigation warrants it; do not bundle or redistribute the aggregated GH data without appropriate permission. Avoid restarting this research as a prerequisite to the current anomaly-reporting work.

### Progetto-SNAPS

SNAPS CatList supplies classification/genre data following the discontinuation of the GH Machine Category INI. `utils/snaps.py` reads classifications from the release SNAPS ZIP. The transformer selects canonical MAME parents having valid GH PORTS, including PORTS available only on a clone. SNAPS classification contributes to publication decisions. The older `Arcade-eligible parents` count is diagnostic; it no longer determines the parent inclusion set. In the GH 2.89a run it was zero while 1,628 parent candidates were selected and 1,564 were publishable. Do not interpret that zero as failed selection without investigating the actual logic.

### Reviewed PS-SNAPS genre vocabulary - separate, completed audit

A separate, three-day review of the MAME 0.289 PS-SNAPS Arcade classifications produced **134 approved Group / Category / Subcategory to introductory-phrase mappings** for LiT. The review covered the classifications currently relevant to LiT and checked the wider non-device MAME parent-machine inventory for those same categories. The final approved workbook is `lit_snaps_classification_review_0289_v96.xlsx`; its **Final approved lookup** worksheet is authoritative. Earlier inventory wording and first-pass sheets are historical, not the approved lookup. The user subsequently reported that a standalone JSON containing the approved mappings had been created for handover to the implementation thread. **Its eventual repository filename, committed state and use by the running transformer have not been verified in this status document**; inspect the live repository before making such claims.

The approved vocabulary uses a **blind lookup**: retain the exact source Group, Category and Subcategory as the key and supply a complete phrase, including its `a` or `an` article. Different keys may share a phrase. Describe the dominant, recognisable gameplay; do not derive prose mechanically from the category hierarchy or `TTL *` hardware prefix, invent per-machine wording overrides, or silently correct questionable PS-SNAPS classifications. The project owner may later add wiki citations documenting the source of apparent category errors. See **DD-014** for examples and integration boundaries.

**Open wording discussion, not yet an approved change:** `Arcade / Driving / Guide and Shoot` (the LaserDisc game *Road Blaster*) was approved as `an interactive driving action arcade video game`. A later conversation proposed `a reaction-based driving arcade video game` so that any future independent LaserDisc `interactive` modifier would not be repeated. The user has **not yet explicitly approved that replacement in this conversation**, so do not silently amend the approved mapping. A general LaserDisc or vector-graphics modifier has likewise not been approved for automatic use. This vocabulary work is independent of the current GH audit-snapshot implementation priority.

### GH INI parent/clone handling

Newer GH INIs may list parent names without clones. The on-disk classification file reflects the source; missing clone classifications can be inherited from parents in memory during transformation. Do not rewrite the source-derived classification file to fabricate clone entries.

## 7. Anomaly detection principles

MHT reports questionable source data for **manual investigation**, not silent correction. Findings should retain rule identifier, machine, section, original source text and revision provenance. Avoid narrow workarounds for real upstream errors.

The GH 2.89a audit (`mht.history.audit_findings`, schema 1.0.0) reported one finding:

```text
rule_id: gh.ports.odd_quotes
machine: sidearmsu
section: PORTS
source_text: [US] PC [MS-DOS, 3.25"] (1991) "Arcade Hits"
```

This **is an intended, correct finding**. The detector already acknowledges balanced quote characters used in recognised disk formats, such as `3.5"` or `5.25"`. The `3.25"` in this particular entry is understood to be an upstream typo requiring manual editing, not a false positive to suppress. It is not proof that all uses of `3.25"` are invalid.

The observed audit also declared detectors `gh.ports.odd_quotes`, `gh.ports.odd_brackets` and `gh.ports.unparsable_date`, each at rule version `1`. A separately logged unexpected `DIGITAL` PORTS category should not be equated automatically with this single finding.

### Historical formatting investigation (GH 0289, before the 2.89a baseline)

An earlier read-only `0289` investigation found 95 GH lines beginning with an asterisk immediately followed by text. Thirty-five Staff occurrences were recognised as 32 emphasised pairs and three standalone subheadings by the Staff-specific parser change at commit `d613278`; its then-current full suite passed 636 tests. The remaining 60 occurrences across 18 systems included apparent missing-space bullets, named-topic candidates and emphasis patterns; these were **investigative candidates, not 60 confirmed upstream defects**. A Tumble Pop Preview screenshot showed a bulleted stage list retaining literal leading asterisks, demonstrating a presentation anomaly that warrants source-versus-parser diagnosis.

Those counts came from manual, read-only investigative scripts and should **not** be conflated with the one finding in the *generated* GH 2.89a History audit. The scripts exposed a reporting-coverage gap: MHT should generate and categorise relevant formatting observations automatically, with useful line evidence, instead of requiring a fresh ad hoc audit every time. Any new detector must have its own rule/version and focused tests; do not assume a regex candidate is a verified GH correction.

### Generated findings versus review decisions

The active `history_audit_findings.json` and `history_parsing_summary.json` provide automated evidence and aggregates. The Preview's `diagnostics.py` and `history_report.py` show selected summary findings, but a bounded overview is not an exhaustive review queue. The immutable revision snapshot helper preserves evidence, not a persistent human decision log. A future review layer should record accepted findings, false positives, requested GH edits and documented local workarounds without changing the active audit or ExoticA output schemas. CSV/spreadsheet output remains desirable as an **export** of generated findings and review outcomes.

### Revision snapshots

`provenance/gh_audit_snapshots.py` preserves a complete active audit report into `summaries/gh_audit_revisions/historyNNN[revision].json`. It validates GH source provenance, checks the ZIP/member, includes archive SHA256 and audit SHA256, and refuses to overwrite a differing snapshot. Identical repeats are harmless. The standalone command remains available for controlled migrations. **Since commit `b4a1e81`, History processing calls the preservation helper after generating its audit and verifying required outputs, but before saving the stage stamp.** `stage_contracts.py` includes the revision snapshot among required History outputs. A failed or conflicting preservation must not create a fresh stage stamp. Integration was covered by four new regression tests; the user confirmed **783 passed, 1 skipped** overall and that the already-snapshotted 2.89a History stage was fresh.

The previously generated active audit is not itself a historical archive. Rebuilding History may replace it. Do not mislabel 2.89a results as original 2.89 findings.

## 8. Evidence and historical comparisons

### Completed generated Wiki release comparison (distinct from anomaly-audit comparisons)

MHT has a committed, read-only `mht diff` command for comparing **generated publication content** in two completed MAME release directories. Its entry point is `src/mht/audit/combined_diff.py::compare_release_content(before, after)`; it composes `release_diff.py` and `trivia_diff.py`. `trivia_details.py` supplies optional human-readable changed-block diagnostics. The CLI supports explicit release pairs, or defaults to the active version and the numerically preceding available release; `--json` is machine-readable, while `--details` and `--machine MACHINE` examine GH Trivia changes. The JSON option is not combined with these human-readable diagnostic options.

The comparison identifies affected generated regions (MAME information panel, MAME titles, opening sentence, PORTS, page names, redirects and GH Trivia sections), plus added or withdrawn publications and page-name changes. Machine identifiers are matched across releases. A page rename is not equivalent to a normal section update, and a withdrawn publication does not imply deletion from MAME. Trivia comparisons use generated renderable blocks and omit parser metadata such as line numbers and detector information. They do **not** assess the correctness of every `history.xml` formatting interpretation. The detailed display uses Python's `difflib` and omits unchanged blocks; it is diagnostic, not a live Wiki editing mechanism.

**Historically verified baseline, 0.288 -> 0.289 (prior to the separate GH 2.89a processing):** 181 modified Wiki records, one newly published, two withdrawn, 184 Wiki-related affected machines, 22 continuing published machines with changed Trivia, five overlapping machines, 17 Trivia-only affected machines, **201 distinct affected machine identifiers**, 35 changed Trivia sections and three page-name changes (`raycris`, `raystorm`, `swa`). These are counts of generated changes, **not** guaranteed unique live Wiki editing operations. The focused regression suite passed **39/39** when the detailed diagnostics were completed. These figures describe those two processed outputs; they must not be presented as the current comparison against the subsequently processed GH 2.89a revision.

**Important distinction:** This completed *content* comparison does **not** implement the planned *anomaly-finding* comparison in DD-010. In particular, it does not compare revision-specific audit snapshots, track detector changes, or establish that a vanished source anomaly was corrected upstream. The ongoing GH audit-snapshot work and future anomaly-review workflow remain separate. See DD-017 for the committed content-diff boundaries.

**Preview integration remains a proposed next step in the dedicated CLI and Preview thread.** Reuse the committed comparison functions and inspect the existing Preview architecture before adding routes or visualisations. Start with the summary and affected-region navigation; do not assume detailed per-machine views or live Wiki actions have been implemented. Keep changes and tests incremental.

### GH 2.89 to 2.89a

Both original and revised archives are staged for `0289`. The user created a prior backup:

`data/backups/0289-before-history289a.zip`

Reported SHA256 of that backup:

`3326fa6d514f50a8e0247cd7994753132931e25d91ef2b6a21dadc35e26a651e`

The user subsequently inspected this backup and recovered its original `history_audit_findings.json`. The original History stamp identified `history289.zip` and its XML member, and the retained archive matched CRC32 `F70F6180` and uncompressed size 64,217,187 bytes. The user reported successful creation of `summaries/gh_audit_revisions/history289.json`, preserving the original 2.89 audit with one finding and declared date 2026-08-07. The existing `history289a.json` snapshot and active 2.89a outputs were not changed. These are user-verified local artefacts, not claimed Git-tracked data.

Verified GH 2.89a member CRC32s from the user's live refresh test:

| ZIP member basename | CRC32 |
| --- | --- |
| `history.xml` | `F5E7419C` |
| `[GAMING HISTORY] Game Or No Game.ini` | `5D2FE73A` |
| `[GAMING HISTORY] Machine Type.ini` | `FE1D636E` |

`[GAMING HISTORY] Machine Category.ini` was absent in both known 2.89 and 2.89a archives.

## 9. Roadmap

### Completed and verified by user's runs

1. GH version discovery and verified acquisition of revision archives.
2. Ingest of `history289a.zip` without discarding `history289.zip`.
3. Highest-revision GH archive selection shared by the stage contracts.
4. Read-only encoding provenance guard and tested automatic cache refresh.
5. Stage-specific cache freshness, including compatibility with old stamps.
6. End-to-end selected-stage rebuild of GH 2.89a with MAME staying fresh.
7. Immutable GH audit snapshot creation with regression coverage; original `history289a.json` preserved manually.
8. **Automatic GH revision snapshot preservation and History output/freshness integration** (commit `b4a1e81`; focused snapshot suite: 12 passed; full suite: 783 passed, 1 skipped).
9. Generated Wiki and GH Trivia release comparisons, including combined machine impact and optional detailed Trivia diagnostics (earlier checkpoint: 39 focused tests passed).

### Next, in order

1. **Optional historical compatibility hardening:** the original GH 2.89 audit has been recovered and source-verified. Determine a safe treatment for *other* older processed releases whose required revision snapshot is missing; do not force wholesale reparsing without justification.
2. **Cross-revision anomaly comparison:** classify findings as new, persisting, apparently resolved or indeterminate. Attribute detector-version changes separately from upstream source edits.
3. **Reporting and review workflow:** automatically generated, individually categorised findings with source evidence; separate persistent review decisions; readable Preview summaries and complete CSV/spreadsheet exports suitable for GH correction work. Keep upstream GH issues, local MAME workarounds and MHT defects distinct. Confirm coverage of formatting anomalies with tests before claiming completeness.
4. **Cross-release tests and cleanup:** cover successive MAME releases, GH suffixes, absent optional INIs, corrupt archives, cache failures, duplicate revisions and legacy stamps.
5. **Documentation alignment:** update stale portions of `README.md` after reviewing current behaviour. Reconstruct `CHANGELOG.md` from verified Git history now that core ZIP acquisition/revision work is complete. Keep the generated-content comparison and anomaly-review workstreams separate.

### Separate Preview workstream

The CLI and Preview Review thread may integrate the committed, read-only content-diff engine into the existing Preview. This is independent of the immediate GH revision-audit snapshot task and must not be confused with unfinished cross-revision anomaly comparison.

### Non-goals for the current increment

- Replacing the working anomaly detectors.
- Creating a separate MAME or GH release directory for each lettered GH revision.
- Duplicating large processed MAME datasets per GH revision.
- Treating every disappeared finding as proof of upstream correction without detector/source comparison.
- Treating the earlier 60 asterisk-pattern observations as 60 confirmed GH defects or as part of the 2.89a generated audit.
- Creating a hand-maintained correction spreadsheet as an alternative source of truth for detector findings.
- Reworking the SNAPS classification architecture or integrating the independently reviewed genre lookup as part of the GH audit-snapshot increment.
- Integrating the 45 MB historical GH Machine Category catalogue as a required input or reconstructing discontinued GH INIs.

## 10. Tests and development safety

Current reported regression baseline: **783 passed, 1 skipped** (15 November 2026, after commit `b4a1e81`). Test counts are historical checkpoints, not guarantees after further changes. Run focused tests first, then `python -m pytest -q`, `git diff --check` and `git status --short` before committing.

Repository development occurs on branch `v2`. Only stage intended files: avoid `git add .` and destructive cleanup. On the user's checkout, the following investigation scripts have previously been deliberately untracked and must be preserved unless the user expressly says otherwise:

- `gh_archive_probe.py`
- `gh_contributions_probe.py`
- `ports_temp.py`
- `prepare_gh_history_archives.py`

Before any historical parsing or migration, verify source selection, active version and backup. A successful test against miniature ZIPs does not replace a controlled live validation.

## 11. Documentation accuracy and maintenance

### Known README drift to review

The current repository README includes general descriptions of GH Machine Category classification and says a stage stamp changes when *any* encoding cache file mtime changes. That no longer fully describes the `v2` implementation. Review the README after accepting these new documents; do not assume all its older descriptions supersede current source code.

### Updating this file

At each meaningful checkpoint:

1. Update **Current development position**, date, regression baseline and next action.
2. Update the affected subsystem and roadmap sections only where behaviour actually changed.
3. Record architectural rationale in `DESIGN_DECISIONS.md` when appropriate.
4. Cite relevant module names and concrete runs; distinguish planned from working.
5. Keep the current section concise even if historical sections grow.

### Evidence basis for this baseline

- The `v2` branch files inspected through GitHub during preparation of this documentation: README, CLI, selected runner, paths, source selection, encoding helpers, stamp helpers, parsers, transformer, SNAPS utility, audit snapshot helper and tool-version registry. The subsequent automatic integration and regression results were supplied by the user, including the commit and status output.
- The committed content-comparison functionality and its 0.288-to-0.289 command/test results were supplied and tested in the separate release-diff development conversation. The baseline figures are historical and have not been re-run against the later GH 2.89a artefacts while updating these documents.
- Reported output and logs from the user's live GH 2.89a runs in the development conversation.
- Prior project handover context for the protected backup and established development constraints.

No full local checkout, git history reconstruction or inspection of the private `data/releases/0289` tree was carried out while revising this document. The automatic integration is supported by the user's checkout logs and commit confirmation; a controlled live rebuild with a new GH revision has not yet been observed. Where further verification matters, it is explicitly deferred.
