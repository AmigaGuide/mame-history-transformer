# src/mht/cli.py
from __future__ import annotations
import argparse
import shutil
from pathlib import Path
from typing import Iterable

from mht.utils.versions import tool_version
from mht.utils.stamps import make_stamp, load_stamp, is_fresh
from mht.utils.paths import (
    DATA_DIR, OUTPUT_DIR, STAMPS_DIR,
    # stage inputs
    MAME_MACHINES_PATH, PARENT_INDEX_PATH, GH_SYSTEM_PORTS_PATH, INI_CLASS_PATH,
    # summaries (used as inputs to transform stamp)
    MAME_SUMMARY, HISTORY_SUMMARY, INI_SUMMARY, TRANSFORM_SUMMARY,
)
from mht.utils.validator import validate as validate_outputs, REGISTRY as VALIDATION_REGISTRY

# Stage-specific config mirroring your modules
STAGES = {
    "mame": {
        "schema_id": "mht.stage.mame",
        "tool_key":  "mame_parser",
        "inputs":    [DATA_DIR / "mame.xml"],
        "stamp":     STAMPS_DIR / "mame.json",
    },
    "history": {
        "schema_id": "mht.stage.history",
        "tool_key":  "history_parser",
        "inputs":    [DATA_DIR / "history.xml"],
        "stamp":     STAMPS_DIR / "history.json",
    },
    "ini": {
        "schema_id": "mht.stage.ini",
        "tool_key":  "ini_summary",
        "inputs":    [DATA_DIR / "[GAMING HISTORY] Game Or No Game.ini",
                      DATA_DIR / "[GAMING HISTORY] Machine Category.ini",
                      DATA_DIR / "[GAMING HISTORY] Machine Type.ini"],
        "stamp":     STAMPS_DIR / "ini.json",
    },
    "transform": {
        "schema_id": "mht.stage.transform",
        "tool_key":  "transformer",
        # must match transformer.py’s stamp_inputs order/paths
        "inputs":    [
            MAME_MACHINES_PATH,
            INI_CLASS_PATH,
            PARENT_INDEX_PATH,
            GH_SYSTEM_PORTS_PATH,
            MAME_SUMMARY,
            HISTORY_SUMMARY,
            INI_SUMMARY,
            DATA_DIR / "title_overrides.json",
        ],
        "stamp":     STAMPS_DIR / "transform.json",
    },
}

def cmd_validate(args: argparse.Namespace) -> int:
    names = args.only or None
    errors = validate_outputs(names)
    if errors:
        print("Validation failed:")
        for e in errors:
            print(e)
        return 1
    print("Validation OK")
    return 0

def _exists_list(paths: Iterable[Path]) -> list[Path]:
    return [p for p in paths if p.exists()]

def cmd_status(args: argparse.Namespace) -> int:
    any_stale = False
    for name, cfg in STAGES.items():
        inputs_all = cfg["inputs"]
        inputs_exist = _exists_list(inputs_all)
        tv = tool_version(cfg["tool_key"])

        current = make_stamp(cfg["schema_id"], tv, inputs=inputs_exist)
        prev = load_stamp(cfg["stamp"])
        fresh = is_fresh(current, prev)

        note = []
        if not inputs_exist:
            note.append("no inputs found")
        if prev is None:
            note.append("no stamp")

        reason = "fresh" if fresh else "stale"
        suffix = f" ({'; '.join(note)})" if note else ""
        #print(f"{name:10} : {reason}{suffix}")
        print(f"{name:10} : {reason}{suffix}  (tool={cfg['tool_key']} v{tv})")

        if not fresh:
            any_stale = True
    return 0 if not any_stale else 1

def _iter_json_children(dir_path: Path) -> list[Path]:
    if not dir_path.exists():
        return []
    out = []
    for p in dir_path.iterdir():
        # only direct children; no recursive delete
        if p.is_file() and p.suffix.lower() == ".json":
            out.append(p)
    return out

def _gather_clean_targets(args) -> list[Path]:
    targets: list[Path] = []

    # Outputs: only JSONs directly under OUTPUT_DIR
    if args.outputs:
        targets += _iter_json_children(OUTPUT_DIR)

    # Stamps: only JSONs directly under STAMPS_DIR
    if args.stamps:
        targets += _iter_json_children(STAMPS_DIR)

    # Data summaries: specific known summary JSONs
    if args.data_summaries:
        for p in (MAME_SUMMARY, HISTORY_SUMMARY, INI_SUMMARY, TRANSFORM_SUMMARY, DATA_DIR / "run_manifest.json"):
            if p.exists() and p.is_file() and p.suffix.lower() == ".json":
                targets.append(p)

    # Deduplicate, stable order
    dedup = []
    seen = set()
    for p in sorted(targets, key=lambda x: str(x).lower()):
        if p not in seen:
            seen.add(p)
            dedup.append(p)
    return dedup


def cmd_clean(args: argparse.Namespace) -> int:
    if not (args.outputs or args.stamps or args.data_summaries):
        print("Nothing to clean. Use one or more of: --outputs --stamps --data-summaries.")
        return 1
        
    targets = _gather_clean_targets(args)

    if not targets:
        print("Nothing to clean. Use --outputs / --stamps / --data-summaries.")
        return 0

    print("The following files would be deleted:")
    for p in targets:
        print("  ", p)

    if args.dry_run:
        print("\nDry-run: nothing deleted.")
        return 0

    if not args.yes:
        resp = input("\nProceed? [y/N] ").strip().lower()
        if resp not in {"y", "yes"}:
            print("Aborted.")
            return 1

    # Perform deletions
    for p in targets:
        try:
            p.unlink(missing_ok=True)
        except Exception as e:
            print(f"Failed to delete {p}: {e}")

    print(f"Deleted {len(targets)} file(s).")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    # Temporary: delegate to main.py for your full incremental pipeline,
    # because it already handles encodings and orchestration correctly.
    # This keeps behaviour identical to today, but via a named subcommand.
    import runpy, sys
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    entry = repo_root / "main.py"
    if (repo_root / "src").exists():
        sys.path.insert(0, str(repo_root / "src"))
    runpy.run_path(str(entry), run_name="__main__")
    return 0

def main() -> None:
    p = argparse.ArgumentParser(prog="mht", description="MAME-History-Transformer CLI")

    # NOT required, so we can have a default
    sub = p.add_subparsers(dest="cmd", required=False)

    # default: run the full pipeline (same as `mht run`)
    p.set_defaults(func=cmd_run)

    s_status = sub.add_parser("status", help="Report freshness (stamp-based) for each stage")
    s_status.set_defaults(func=cmd_status)

    s_clean = sub.add_parser("clean", help="Remove outputs/stamps/summaries")
    s_clean.add_argument("--dry-run", action="store_true",
                         help="Show what would be deleted, without deleting")
    s_clean.add_argument("--yes", action="store_true",
                         help="Do not ask for confirmation (non-interactive)")
    s_clean.add_argument("--outputs", action="store_true", help="Delete output/ artefacts")
    s_clean.add_argument("--stamps", action="store_true", help="Delete data/.stamps/ files")
    s_clean.add_argument("--data-summaries", action="store_true",
                         help="Delete data/*_summary.json and run_manifest.json")
    s_clean.set_defaults(func=cmd_clean)

    s_run = sub.add_parser("run", help="Run the full incremental pipeline (delegates to main.py)")
    s_run.set_defaults(func=cmd_run)

    # ... after s_run setup ...
    s_validate = sub.add_parser("validate", help="Validate output JSONs against schemas")
    s_validate.add_argument(
        "--only",
        nargs="+",
        choices=sorted(VALIDATION_REGISTRY.keys()),   # was SCHEMAS.keys()
        help="Limit validation to one or more of: " + ", ".join(sorted(VALIDATION_REGISTRY.keys())),
    )
    s_validate.set_defaults(func=cmd_validate)

    args = p.parse_args()
    raise SystemExit(args.func(args))

if __name__ == "__main__":
    main()
