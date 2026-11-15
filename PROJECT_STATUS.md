# MHT - Project Status

**Project:** MAME-History-Transformer (MHT)  
**Repository:** `AmigaGuide/mame-history-transformer`  
**Development branch:** `v2`  
**Baseline date:** 15 November 2026  
**Status:** Working baseline for documentation review, not an implementation change  
**Companion:** `DESIGN_DECISIONS.md`

> **Read this first when resuming development.** This document records the verified v2 architecture, known operational state and unfinished work. Source code and passing tests are authoritative for executable behaviour. Decisions are explained separately in `DESIGN_DECISIONS.md`. Update the current position after each substantial development increment, and distinguish verified facts from intentions.

## 1. Current development position

### Latest confirmed results

- The user reports a full regression suite of **779 passed, 1 skipped** after introducing the GH audit snapshot utility. The new snapshot tests passed **8/8**. These are results from the user's Windows checkout, not a suite run during preparation of this document.
- The user reports `python -m mht status --version 0289` showing **INI, MAME, History and Transform all fresh** after processing `history289a.zip`.
- The selected GH revision is `history289a.zip`; the original `history289.zip` is retained in the same release archives directory.
- The revised History XML declares **2.89a**, dated **2026-11-09**. The archive's History, Game Or No Game and Machine Type members have been verified against their ZIP CRC32 values.
- MAME parsing was **not** repeated for this GH revision. Its provenance stayed unchanged and its stage remained fresh.
- An immutable audit snapshot was created at `data/releases/0289/summaries/gh_audit_revisions/history289a.json` using the standalone snapshot command.
- Snapshot creation is **not yet automatic** in the History processing stage. That is the next planned increment.

### Immediate next development task

Integrate `preserve_gh_audit_snapshot(...)` into successful History processing, with tests for failure behaviour and existing snapshots. The existing audit detector logic and ExoticA output formats must remain unchanged. Do **not** assume a snapshot for the original `history289.zip` already exists - inspect the previous release backup or original audit first.

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
| `src/mht/provenance/gh_audit_snapshots.py` | Manual, source-verified immutable audit snapshots |
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

### Progetto-SNAPS

SNAPS CatList supplies classification/genre data following the discontinuation of the GH Machine Category INI. `utils/snaps.py` reads classifications from the release SNAPS ZIP. The transformer selects canonical MAME parents having valid GH PORTS, including PORTS available only on a clone. SNAPS classification contributes to publication decisions. The older `Arcade-eligible parents` count is diagnostic; it no longer determines the parent inclusion set. In the GH 2.89a run it was zero while 1,628 parent candidates were selected and 1,564 were publishable. Do not interpret that zero as failed selection without investigating the actual logic.

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

### Revision snapshots

`provenance/gh_audit_snapshots.py` can preserve a complete active audit report into `summaries/gh_audit_revisions/historyNNN[revision].json`. It validates GH source provenance, checks the ZIP/member, includes archive SHA256 and audit SHA256, and refuses to overwrite a differing snapshot. Identical repeats are harmless. This is currently **manual only**; the intended integration point is after History outputs and audit succeed, before a successful stage stamp is recorded.

The previously generated active audit is not itself a historical archive. Rebuilding History may replace it. Do not mislabel 2.89a results as original 2.89 findings.

## 8. Evidence and historical comparisons

### GH 2.89 to 2.89a

Both original and revised archives are staged for `0289`. The user created a prior backup:

`data/backups/0289-before-history289a.zip`

Reported SHA256 of that backup:

`3326fa6d514f50a8e0247cd7994753132931e25d91ef2b6a21dadc35e26a651e`

This backup was created before the revised source was ingested. **Its contents have not been re-inspected for this documentation draft**; verify it before relying on any presumed original audit. No claim is made that a version 2.89 snapshot has already been recovered.

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
7. Manual immutable GH audit snapshot creation with regression coverage.

### Next, in order

1. **Automatic snapshot preservation:** only after successful History audit writing; refuse conflicting snapshots and do not mark stage fresh on a snapshot failure. Consider the stamp and output-write ordering carefully.
2. **Recover original GH 2.89 audit evidence:** inspect the pre-revision backup, validate original source provenance, and preserve only genuinely attributable data.
3. **Cross-revision comparison:** classify findings as new, persisting, apparently resolved or indeterminate. Attribute detector-version changes separately from upstream source edits.
4. **Reporting:** readable summaries, source text and provenance, and CSV output suitable for manual GH correction workflows.
5. **Cross-release tests and cleanup:** cover successive MAME releases, GH suffixes, absent optional INIs, corrupt archives, cache failures, duplicate revisions and legacy stamps.
6. **Documentation alignment:** update stale portions of `README.md` after the new docs are reviewed.

### Non-goals for the current increment

- Replacing the working anomaly detectors.
- Creating a separate MAME or GH release directory for each lettered GH revision.
- Duplicating large processed MAME datasets per GH revision.
- Treating every disappeared finding as proof of upstream correction without detector/source comparison.
- Reworking the SNAPS classification architecture.

## 10. Tests and development safety

Current reported regression baseline: **779 passed, 1 skipped** (15 November 2026). Test counts are historical checkpoints, not guarantees after further changes. Run focused tests first, then `python -m pytest -q`, `git diff --check` and `git status --short` before committing.

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

- The current `v2` branch files reviewed through GitHub: README, CLI, selected runner, paths, source selection, encoding helpers, stamp helpers, parsers, transformer, SNAPS utility, audit snapshot helper and tool-version registry.
- Reported output and logs from the user's live GH 2.89a runs in the development conversation.
- Prior project handover context for the protected backup and established development constraints.

No full local checkout, git history reconstruction or inspection of the private `data/releases/0289` tree was carried out while drafting this document. Where that matters, verification is explicitly deferred.
