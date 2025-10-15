# Data folder

This folder holds the versioned datasets and a few shared reference files used by the transformer. Source files are supplied locally; generated artefacts are not committed to Git.

## Do not commit large data

Keep these out of Git:

* MAME and Gaming-History ZIPs
* Extracted XML/INI source files
* Generated summaries, outputs, and stamps
* Logs and temporary files

Only small reference JSON, schemas, and catalogues live in the repo.

## First-run workflow (drop-zone intake)

1. Place the two ZIP archives for a single MAME release in:

   * `data/incoming/`
   * Example: `mame0280lx.zip`, `history280.zip`
2. Run the intake command (see project README). It will:

   * Detect the MAME version key (e.g. `0280`)
   * Create `data/releases/0280/{archives,extracted,summaries,outputs,.stamps}`
   * Move your ZIPs into `data/releases/0280/archives/`
3. Until ZIP-streaming is enabled, manually place the extracted source files in:

   * `data/releases/0280/extracted/`
   * Canonical filenames:

     * `mame.xml`
     * `history.xml`
     * `[GAMING HISTORY] Game Or No Game.ini`
     * `[GAMING HISTORY] Machine Category.ini`
     * `[GAMING HISTORY] Machine Type.ini`
4. Run the pipeline. It will:

   * Record encodings and visible version strings in `data/releases/0280/manifest.json`
   * Produce summaries and outputs under the release
   * Write stage stamps in `.stamps/`
   * Update `data/releases_index.json`

## Per-release layout

```
data/
  releases/
    0280/
      archives/      # the two ZIPs for this release (if used)
      extracted/     # mame.xml, history.xml, three GH INIs (flat, unique names)
      summaries/     # parsing and transform summaries (generated)
      outputs/       # final JSON outputs (generated)
      .stamps/       # one JSON stamp per stage (generated)
      manifest.json  # source encodings, versions, hashes, pipeline pointers
```

Notes:

* Encodings and version strings are recorded in each release’s `manifest.json`.
* No top-level `output/`. Outputs always live under `data/releases/<ver>/outputs/`.

## Version catalogue

* `data/releases_index.json` — an array listing all discovered releases with status flags (initialised, inputs ready, parsed, transformed, validated, active).

## Shared reference data

* `data/lookups/` — version-independent reference files (tracked):

  * `title_overrides.json` and other normalisation or alias maps
* `data/schemas/` — JSON Schemas for manifests, catalogues, outputs, and summaries (tracked)

## Operational folders

* `data/incoming/` — drop-zone for ZIP intake
* `data/quarantine/` — where invalid or mismatched files are moved (rare)
* `data/tmp/` — scratch space

## What this replaces

* No global `encodings.json` — encoding and version details are per-release in `manifest.json`.
* No flat `data/mame.xml`, `data/history.xml`, or INIs — use `data/releases/<ver>/extracted/` instead.
* No top-level `/output` — use `data/releases/<ver>/outputs/`.
