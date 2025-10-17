from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Optional

from mht.utils.versions import tool_version
from mht.utils.stamps import make_stamp, load_stamp, is_fresh
from mht.utils.paths import (
    # repo/data roots
    DATA_DIR,
    # active version & dirs
    active_version,
    ensure_release_dirs,
    release_root,
    archives_dir,
    extracted_dir,
    outputs_dir,
    summaries_dir,
    stamps_dir,
    # per-release artefacts
    mame_xml_path,
    history_xml_path,
    ini_game_path,
    ini_category_path,
    ini_type_path,
    mame_machines_path,
    parent_index_path,
    gh_system_ports_path,
    ini_classifications_path,
    mame_summary_path,
    history_summary_path,
    ini_summary_path,
    transform_summary_path,
    exotica_wiki_path,
    exotica_raw_path,
    exotica_pages_path,
    # shared lookups
    title_overrides_path,
    # shims (legacy)
    RUN_MANIFEST,  # still points to summaries/run_manifest.json via shim
)
from mht.utils.validator import validate as validate_outputs, REGISTRY as VALIDATION_REGISTRY

# Optional imports for new commands (guarded so CLI still works if files aren’t present yet)
try:
    from mht.provenance.archives import import_incoming_archives
except Exception:  # pragma: no cover
    import_incoming_archives = None  # type: ignore

try:
    from mht.provenance.releases_index import refresh_releases_index
except Exception:  # pragma: no cover
    refresh_releases_index = None  # type: ignore


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def _exists_list(paths: Iterable[Path]) -> list[Path]:
    return [p for p in paths if p.exists()]

def _iter_json_children(dir_path: Path) -> list[Path]:
    if not dir_path.exists():
        return []
    out: list[Path] = []
    for p in dir_path.iterdir():
        if p.is_file() and p.suffix.lower() == ".json":
            out.append(p)
    return out

def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))

def _ver_or_active(ver: Optional[str]) -> str:
    return active_version(ver)


# --------------------------------------------------------------------------------------
# Status (stamp freshness) per-stage for the ACTIVE release
# --------------------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> int:
    ver = _ver_or_active(args.version)
    ensure_release_dirs(ver)

    # Stage “tool keys” for version display
    tools = {
        "ini":        "ini_summary",
        "mame":       "mame_parser",
        "history":    "history_parser",
        "transform":  "transformer",
    }

    # Build per-stage inputs & stamp (per release)
    stage_cfg = {
        "ini": {
            "schema_id": "mht.stage.ini",
            "inputs": [
                ini_game_path(ver),
                ini_category_path(ver),
                ini_type_path(ver),
                summaries_dir(ver) / "encodings.json",  # not strictly used; included for parity if you later move it
            ],
            "stamp": stamps_dir(ver) / "ini.json",
        },
        "mame": {
            "schema_id": "mht.stage.mame",
            "inputs": [
                mame_xml_path(ver),
                summaries_dir(ver) / "encodings.json",
            ],
            "stamp": stamps_dir(ver) / "mame.json",
        },
        "history": {
            "schema_id": "mht.stage.history",
            "inputs": [
                history_xml_path(ver),
                summaries_dir(ver) / "encodings.json",
            ],
            "stamp": stamps_dir(ver) / "history.json",
        },
        "transform": {
            "schema_id": "mht.stage.transform",
            "inputs": [
                mame_machines_path(ver),
                ini_classifications_path(ver),
                parent_index_path(ver),
                gh_system_ports_path(ver),
                mame_summary_path(ver),
                history_summary_path(ver),
                ini_summary_path(ver),
                title_overrides_path(),  # global lookup
            ],
            "stamp": stamps_dir(ver) / "transform.json",
        },
    }

    any_stale = False
    print(f"[status] active release = {ver}  (root: {release_root(ver).as_posix()})\n")

    for name, cfg in stage_cfg.items():
        inputs_exist = _exists_list(cfg["inputs"])
        tv = tool_version(tools[name])

        current = make_stamp(cfg["schema_id"], tv, inputs=inputs_exist)
        prev = load_stamp(cfg["stamp"])
        fresh = is_fresh(current, prev)

        note = []
        if not inputs_exist:
            note.append("no inputs found")
        if prev is None:
            note.append("no stamp")

        suffix = f" ({'; '.join(note)})" if note else ""
        print(f"{name:10} : {'fresh' if fresh else 'stale'}{suffix}  (tool={tools[name]} v{tv})")

        if not fresh:
            any_stale = True

    return 0 if not any_stale else 1


# --------------------------------------------------------------------------------------
# Clean (per-release)
# --------------------------------------------------------------------------------------

def _gather_clean_targets(args: argparse.Namespace, ver: str) -> list[Path]:
    targets: list[Path] = []

    if args.outputs:
        targets += _iter_json_children(outputs_dir(ver))

    if args.stamps:
        targets += _iter_json_children(stamps_dir(ver))

    if args.data_summaries:
        # known summary JSONs + run_manifest (now under summaries/)
        for p in (
            mame_summary_path(ver),
            history_summary_path(ver),
            ini_summary_path(ver),
            transform_summary_path(ver),
            RUN_MANIFEST,  # shim points to summaries/run_manifest.json
        ):
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
    ver = _ver_or_active(args.version)
    ensure_release_dirs(ver)

    if not (args.outputs or args.stamps or args.data_summaries):
        print("Nothing to clean. Use one or more of: --outputs --stamps --data-summaries.")
        return 1

    targets = _gather_clean_targets(args, ver)
    if not targets:
        print("Nothing to clean.")
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

    for p in targets:
        try:
            p.unlink(missing_ok=True)
        except Exception as e:
            print(f"Failed to delete {p}: {e}")

    print(f"Deleted {len(targets)} file(s).")
    return 0


# --------------------------------------------------------------------------------------
# Validate (unchanged)
# --------------------------------------------------------------------------------------

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


# --------------------------------------------------------------------------------------
# Run (delegate to your existing main.py)
# --------------------------------------------------------------------------------------

def cmd_run(_: argparse.Namespace) -> int:
    import runpy, sys
    repo_root = Path(__file__).resolve().parents[2]
    entry = repo_root / "main.py"
    if (repo_root / "src").exists():
        sys.path.insert(0, str(repo_root / "src"))
    runpy.run_path(str(entry), run_name="__main__")
    return 0


# --------------------------------------------------------------------------------------
# New: ingest archives from data/incoming/
# --------------------------------------------------------------------------------------

def cmd_ingest(args: argparse.Namespace) -> int:
    if import_incoming_archives is None:
        print("The 'ingest' command requires mht.provenance.archives.import_incoming_archives to be present.")
        return 2

    ver = _ver_or_active(args.version)
    incoming = Path(args.incoming) if args.incoming else (DATA_DIR / "incoming")
    ensure_release_dirs(ver)

    res = import_incoming_archives(incoming=incoming, extract=(not args.no_extract), version=ver)
    _print_json(res)
    return 0 if res.get("ok") else 1


# --------------------------------------------------------------------------------------
# New: rebuild releases_index.json
# --------------------------------------------------------------------------------------

def cmd_releases_index(_: argparse.Namespace) -> int:
    if refresh_releases_index is None:
        print("The 'releases-index' command requires mht.provenance.releases_index.refresh_releases_index.")
        return 2
    doc = refresh_releases_index()
    _print_json(doc)
    return 0


# --------------------------------------------------------------------------------------
# Argparse
# --------------------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(prog="mht", description="MAME-History-Transformer CLI")
    sub = p.add_subparsers(dest="cmd", required=False)

    # default: run the full pipeline
    p.set_defaults(func=cmd_run)

    # status
    s_status = sub.add_parser("status", help="Report freshness (stamp-based) for the active (or given) release")
    s_status.add_argument("--version", "-v", help="Release version (e.g. 0280). Defaults to active_version().")
    s_status.set_defaults(func=cmd_status)

    # clean
    s_clean = sub.add_parser("clean", help="Remove outputs/stamps/summaries for the active (or given) release")
    s_clean.add_argument("--version", "-v", help="Release version to clean (default: active)")
    s_clean.add_argument("--dry-run", action="store_true", help="Show what would be deleted, without deleting")
    s_clean.add_argument("--yes", action="store_true", help="Do not ask for confirmation")
    s_clean.add_argument("--outputs", action="store_true", help="Delete outputs/ artefacts")
    s_clean.add_argument("--stamps", action="store_true", help="Delete .stamps/ files")
    s_clean.add_argument("--data-summaries", action="store_true", help="Delete *_summary.json and run_manifest.json")
    s_clean.set_defaults(func=cmd_clean)

    # run
    s_run = sub.add_parser("run", help="Run the full incremental pipeline (delegates to main.py)")
    s_run.set_defaults(func=cmd_run)

    # validate
    s_validate = sub.add_parser("validate", help="Validate output JSONs against schemas")
    s_validate.add_argument(
        "--only",
        nargs="+",
        choices=sorted(VALIDATION_REGISTRY.keys()),
        help="Limit validation to one or more of: " + ", ".join(sorted(VALIDATION_REGISTRY.keys())),
    )
    s_validate.set_defaults(func=cmd_validate)

    # NEW: ingest
    s_ingest = sub.add_parser("ingest", help="Import archives from data/incoming/ into releases/<ver>/archives and (optionally) extract")
    s_ingest.add_argument("--version", "-v", help="Release version to ingest into (default: active)")
    s_ingest.add_argument("--incoming", help="Override incoming directory (default: data/incoming)")
    s_ingest.add_argument("--no-extract", action="store_true", help="Do not extract after moving")
    s_ingest.set_defaults(func=cmd_ingest)

    # NEW: releases-index
    s_idx = sub.add_parser("releases-index", help="Rebuild data/releases_index.json")
    s_idx.set_defaults(func=cmd_releases_index)

    args = p.parse_args()
    raise SystemExit(args.func(args))

if __name__ == "__main__":
    main()
