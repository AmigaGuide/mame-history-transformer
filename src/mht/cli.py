from __future__ import annotations

import argparse
from argparse import RawTextHelpFormatter
import json
from pathlib import Path
from typing import Iterable, Optional
import datetime

from mht.utils.versions import tool_version
from mht.utils.stamps import make_stamp, load_stamp, is_fresh
from mht.utils.paths import (
    # repo/data roots
    DATA_DIR, OUTPUT_DIR, STAMPS_DIR,
    # active version & dirs
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
    # add new helpers:
    incoming_dir, quarantine_dir, set_active_version, active_version, list_release_versions, encodings_cache_path,
    ENCODINGS_JSON,
)
from mht.utils.validator import validate as validate_outputs, REGISTRY as VALIDATION_REGISTRY
from mht.provenance.peek import sniff_history_xml, sniff_mame_xml, sniff_ini_file
from mht.provenance.archives import import_incoming_archives, list_incoming_archives, verify_and_stage_zip
from mht.provenance.releases_index import rebuild_releases_index

# --------------------------------------------------------------------------------------
# Incoming handlers
# --------------------------------------------------------------------------------------

def cmd_incoming_verify(args: argparse.Namespace) -> int:
    inc = incoming_dir()
    zips = list_incoming_archives(inc)
    if not zips:
        print(f"(no zip files in {inc})")
        return 0

    print(f"Verifying archives in {inc}...")
    any_fail = False
    for zp in zips:
        # verify_and_stage_zip returns Path | None
        dest = verify_and_stage_zip(zp, args.version)
        name = zp.name
        if dest is not None:
            # dest is release_root(<ver>), file was copied to archives/<name>
            print(f"  OK:   {name}  → {dest / 'archives' / name}")
        else:
            any_fail = True
            print(f"  FAIL: {name} (moved to quarantine)")

    return 1 if any_fail else 0


def cmd_incoming_import(args: argparse.Namespace) -> int:
    # Moves/copies into data/releases/<ver>/archives, extracts, and updates index
    ok, results = import_incoming_archives(
        target_version=args.version,
        mode=("move" if args.move else "copy"),
        quarantine_on_fail=True,
        dry_run=args.dry_run,
    )

    action = "DRY-RUN import" if args.dry_run else "Import"
    print(f"{action} results for version {args.version or '(auto)'}:")
    if not results:
        print("  (nothing to do)")
        return 0 if ok else 1

    failures = 0
    for r in results:
        name = r.get("name") or "(unknown.zip)"
        status = r.get("status") or "unknown"
        msg = r.get("message") or ""
        if status == "ok":
            where = r.get("release_root")
            print(f"  ✔ {name}  →  {where}  {f'({msg})' if msg else ''}")
        else:
            failures += 1
            print(f"  ✖ {name}  —  {msg}")

    return 1 if failures else (0 if ok else 1)

def cmd_incoming_scan(args: argparse.Namespace) -> int:
    inc = incoming_dir()
    items = list_incoming_archives(inc)
    print(f"Incoming archives in {inc}:")
    if not items:
        print("  (none)")
        return 0

    for p in items:
        try:
            st = p.stat()
            mtime_utc = datetime.datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z"
            print(f"  {p.name:30}  {st.st_size:>10} bytes  mtime={mtime_utc}")
        except FileNotFoundError:
            print(f"  {p.name:30}  (missing)")
    return 0

def cmd_incoming_adopt(args: argparse.Namespace) -> int:
    dest = verify_and_stage_zip(args.zip, args.version)
    if dest is not None:
        print(f"Adopted: {dest / 'archives' / args.zip.name}")
        return 0
    print("Adoption failed (file moved to quarantine).")
    return 2

# --------------------------------------------------------------------------------------
# Incoming handlers
# --------------------------------------------------------------------------------------

def cmd_releases_list(args: argparse.Namespace) -> int:
    current = None
    try:
        current = active_version()
    except Exception:
        pass
    versions = list_release_versions()
    if not versions:
        print("(no releases found)")
        return 0
    print("Releases:")
    for v in versions:
        mark = " *" if v == current else ""
        print(f"  {v}{mark}")
    if current:
        print(f"\nActive: {current}")
    return 0

def cmd_releases_set(args: argparse.Namespace) -> int:
    set_active_version(args.version)
    print(f"Active version set to {args.version}")
    return 0

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

def _find_archive_for(ver: str, prefer_token: str) -> Path | None:
    """
    Find a staged ZIP in releases/<ver>/archives that contains prefer_token in its name.
    Falls back to the first .zip if none match. Returns None if no archives exist.
    """
    arc = archives_dir(ver)
    if not arc.exists():
        return None
    zips = sorted(arc.glob("*.zip"), key=lambda p: p.name.lower())
    preferred = [p for p in zips if prefer_token.lower() in p.name.lower()]
    return (preferred[0] if preferred else (zips[0] if zips else None))

def _exists_list_safe(items: list[Path | None]) -> list[Path]:
    """Filter to existing Paths only; tolerate None entries."""
    return [p for p in items if isinstance(p, Path) and p.exists()]

def _ver_or_active(ver: Optional[str]) -> str:
    """Return <ver> if provided, else the currently active release key (e.g. '0281')."""
    return ver or active_version()

def _read_json_safe(p: Path) -> Optional[dict]:
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None
    
# --------------------------------------------------------------------------------------
# Status (stamp freshness) per-stage for the ACTIVE release
# --------------------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> int:
    ver = _ver_or_active(args.version)
    ensure_release_dirs(ver)

    tools = {
        "ini":        "ini_summary",
        "mame":       "mame_parser",
        "history":    "history_parser",
        "transform":  "transformer",
    }

    # Prefer staged ZIPs (ZIP-first world); fall back to legacy extracted files if present
    mame_zip    = _find_archive_for(ver, "mame")
    history_zip = _find_archive_for(ver, "history")

    # Build per-stage inputs exactly like the runners now do
    enc_cache = encodings_cache_path(ver)

    stage_cfg = {
        "ini": {
            "schema_id": "mht.stage.ini",
            "inputs": _exists_list_safe([history_zip, enc_cache]),
            "stamp": stamps_dir(ver) / "ini.json",
        },
        "mame": {
            "schema_id": "mht.stage.mame",
            "inputs": _exists_list_safe([mame_zip, enc_cache]) or _exists_list_safe([mame_xml_path(ver), enc_cache]),
            "stamp": stamps_dir(ver) / "mame.json",
        },
        "history": {
            "schema_id": "mht.stage.history",
            "inputs": _exists_list_safe([history_zip, enc_cache]) or _exists_list_safe([history_xml_path(ver), enc_cache]),
            "stamp": stamps_dir(ver) / "history.json",
        },
        "transform": {
            "schema_id": "mht.stage.transform",
            "inputs": _exists_list_safe([
                mame_machines_path(ver),
                ini_classifications_path(ver),
                parent_index_path(ver),
                gh_system_ports_path(ver),
                mame_summary_path(ver),
                history_summary_path(ver),
                ini_summary_path(ver),
                title_overrides_path(),
            ]),
            "stamp": stamps_dir(ver) / "transform.json",
        },
    }

    any_stale = False
    print(f"[status] active release = {ver}  (root: {release_root(ver).as_posix()})\n")

    for name, cfg in stage_cfg.items():
        tv = tool_version(tools[name])

        # Make a current stamp snapshot using the inputs that actually exist
        inputs_exist = cfg["inputs"]
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
# ingest archives from data/incoming/
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
# rebuild releases_index.json
# --------------------------------------------------------------------------------------

def cmd_releases_root(args: argparse.Namespace) -> int:
    # print the subparser help if no subcmd is given
    print(args._releases_parser.format_help())
    return 2

def cmd_releases_index(_: argparse.Namespace) -> int:
    entries = rebuild_releases_index()
    print(f"Indexed {len(entries)} release(s). See data/releases_index.json")
    return 0


def cmd_releases_info(args: argparse.Namespace) -> int:
    ver = _ver_or_active(args.version)
    root = release_root(ver)

    paths = {
        "archives":  archives_dir(ver),
        "summaries": summaries_dir(ver),
        "outputs":   outputs_dir(ver),
        "stamps":    stamps_dir(ver),
        "encodings": encodings_cache_path(ver),
        "manifest":  root / "manifest.json",
    }
    print(f"Release: {ver}  Current: {'yes' if ver == active_version() else 'no'}")
    print("Paths:")
    for k, p in paths.items():
        sfx = ""
        if isinstance(p, Path) and p.exists():
            try:
                if p.is_file():
                    sfx = f"  [{p.stat().st_size} bytes]"
            except Exception:
                pass
            print(f"  {k:9}: {p.as_posix()}{sfx}")
        else:
            print(f"  {k:9}: {p.as_posix() if isinstance(p, Path) else str(p)}  (missing)")

    # Try to show quick stats from summaries/outputs if present
    mame_sum = _read_json_safe(mame_summary_path(ver)) or {}
    hist_sum = _read_json_safe(history_summary_path(ver)) or {}
    ini_sum  = _read_json_safe(ini_summary_path(ver)) or {}
    tr_sum   = _read_json_safe(transform_summary_path(ver)) or {}
    wiki     = _read_json_safe(exotica_wiki_path(ver)) or {}
    pages    = _read_json_safe(exotica_pages_path(ver)) or {}

    print("\nStages (presence):")
    stage_presence = {
        "history_ini": bool(ini_sum),
        "mame_parse":  bool(mame_sum),
        "history_xml": bool(hist_sum),
        "transform":   bool(tr_sum),
    }
    for k, ok in stage_presence.items():
        print(f"  {k:12} {'✓' if ok else '–'}")

    def _get(d, *keys, default=None):
        cur = d
        for k in keys:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(k)
        return cur if cur is not None else default

    print("\nQuick stats:")
    total_machines = _get(mame_sum, "totals", "total_machines")
    total_parents  = _get(mame_sum, "totals", "total_parents")
    gh_entries     = (_get(hist_sum, "totals", "systems_total", default=0) or 0) + \
                     (_get(hist_sum, "totals", "software_total", default=0) or 0)
    wiki_pages     = len((_get(wiki, "games", default={}) or {}))
    redirects_cnt  = len((_get(pages, "redirects", default=[]) or []))

    print(f"  mame_machines: {total_machines}   parents: {total_parents}")
    print(f"  gh_entries   : {gh_entries}")
    print(f"  wiki pages   : {wiki_pages}   redirects: {redirects_cnt}")

    # Encodings cache sha (if manifest has it)
    manifest = _read_json_safe(paths["manifest"]) or {}
    enc = manifest.get("encoding_cache") or {}
    if enc:
        print(f"\nEncodings cache: {enc.get('path')}  sha256={enc.get('sha256')}")

    return 0

def cmd_releases_prune(args: argparse.Namespace) -> int:
    keep = max(1, int(args.keep or 2))
    protect_current = not args.no_protect_current

    versions = list_release_versions() or []
    if not versions:
        print("(no releases found)")
        return 0

    # Sort descending (newest first) assuming your keys are comparable strings '0281' > '0280'
    versions = sorted(versions, reverse=True)

    current = None
    try:
        current = active_version()
    except Exception:
        pass

    to_keep = set(versions[:keep])
    to_remove = [v for v in versions[keep:] if not (protect_current and current and v == current)]

    if not to_remove:
        print(f"Nothing to prune. Keeping: {', '.join(sorted(to_keep))}")
        return 0

    print("Prune plan:")
    for v in to_remove:
        root = release_root(v)
        size = 0
        for p in root.rglob("*"):
            try:
                if p.is_file():
                    size += p.stat().st_size
            except Exception:
                pass
        print(f"  remove {root.as_posix()}  (~{size} bytes)")

    if args.dry_run:
        print("\nDry-run: nothing deleted.")
        return 0

    if not args.yes:
        resp = input("\nProceed with deletion? [y/N] ").strip().lower()
        if resp not in {"y", "yes"}:
            print("Aborted.")
            return 1

    import shutil
    failed = 0
    for v in to_remove:
        try:
            shutil.rmtree(release_root(v), ignore_errors=False)
            print(f"Removed: {release_root(v).as_posix()}")
        except Exception as e:
            failed += 1
            print(f"Failed to remove {release_root(v)}: {e}")

    # Rebuild index if available
    try:
        rebuild_releases_index()
    except Exception:
        pass

    return 1 if failed else 0

def cmd_releases_gc(args: argparse.Namespace) -> int:
    base = DATA_DIR / "releases"
    if not base.exists():
        print("(no releases dir)")
        return 0

    empties = []
    for d in sorted(base.rglob("*"), key=lambda p: len(p.as_posix().split("/")), reverse=True):
        try:
            if d.is_dir() and not any(d.iterdir()):
                empties.append(d)
        except Exception:
            pass

    if not empties:
        print("No empty directories to remove.")
        return 0

    print("Empty directories:")
    for d in empties:
        print("  ", d.as_posix())

    if args.dry_run:
        print("\nDry-run: nothing deleted.")
        return 0

    for d in empties:
        try:
            d.rmdir()
        except Exception as e:
            print(f"Failed to remove {d}: {e}")

    print(f"Removed {len(empties)} empty directorie(s).")
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

    # incoming
    s_incoming = sub.add_parser("incoming", help="Manage incoming ZIP archives")
    s_incoming_sub = s_incoming.add_subparsers(dest="subcmd", required=True)

    s_inc_scan = s_incoming_sub.add_parser("scan", help="List ZIPs in data/incoming")
    s_inc_scan.set_defaults(func=cmd_incoming_scan)

    s_inc_adopt = s_incoming_sub.add_parser("adopt", help="Verify + move/copy a ZIP into a release")
    s_inc_adopt.add_argument("zip", type=Path, help="Path to the ZIP in data/incoming")
    s_inc_adopt.add_argument("--version", required=True, help="Target release version, e.g. 0280")
    s_inc_adopt.add_argument("--copy", action="store_true", help="Copy instead of move")
    s_inc_adopt.set_defaults(func=cmd_incoming_adopt)

    # incoming verify (check all ZIPs without modifying anything)
    s_inc_verify = s_incoming_sub.add_parser("verify", help="Verify ZIPs are valid before import")
    s_inc_verify.add_argument("--version", help="Target MAME version (e.g. 0280). If omitted, infer per archive.")
    s_inc_verify.set_defaults(func=cmd_incoming_verify)

    # incoming import (ingest all valid ZIPs; copy by default)
    s_inc_import = s_incoming_sub.add_parser("import", help="Ingest valid ZIPs into releases/<ver>/archives and extract")
    s_inc_import.add_argument("--version", help="Target MAME version (e.g. 0280). If omitted, infer per archive.")
    s_inc_import.add_argument("--move", action="store_true", help="Move files instead of copying")
    s_inc_import.add_argument("--dry-run", action="store_true", help="Show what would happen without writing")
    s_inc_import.set_defaults(func=cmd_incoming_import)

    # releases
    s_rel = sub.add_parser("releases", help="Inspect and manage releases")
    s_rel_sub = s_rel.add_subparsers(dest="subcmd", required=True)

    # stash the parser so the handler can print help
    s_rel.set_defaults(func=cmd_releases_root, _releases_parser=s_rel)

    s_rel_idx = s_rel_sub.add_parser("index", help="Rebuild data/releases_index.json")
    s_rel_idx.set_defaults(func=cmd_releases_index)

    s_rel_list = s_rel_sub.add_parser("list", help="List discovered releases; marks active one")
    s_rel_list.set_defaults(func=cmd_releases_list)

    s_rel_set = s_rel_sub.add_parser("set", help="Set active version (writes data/current_version.txt)")
    s_rel_set.add_argument("version", help="Release version, e.g. 0280")
    s_rel_set.set_defaults(func=cmd_releases_set)
               
    # releases info
    s_rel_info = s_rel_sub.add_parser("info", help="Show details for a release (default: active)")
    s_rel_info.add_argument("--version", "-v", help="Release key, e.g. 0281 (default: active)")
    s_rel_info.set_defaults(func=cmd_releases_info)

    s_rel_info.epilog = """Examples:
      mht releases info           # Show info for the active release
      mht releases info -v 0280   # Show info for release 0280
    """
    
    # releases prune
    s_rel_prune = s_rel_sub.add_parser("prune", help="Delete older releases (keep newest N)")
    s_rel_prune.add_argument("--keep", type=int, default=2, help="Number of newest releases to keep (default: 2)")
    s_rel_prune.add_argument("--no-protect-current", action="store_true", help="Allow pruning the current release")
    s_rel_prune.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    s_rel_prune.add_argument("--yes", action="store_true", help="Do not ask for confirmation")
    s_rel_prune.set_defaults(func=cmd_releases_prune)

    # releases gc
    s_rel_gc = s_rel_sub.add_parser("gc", help="Remove empty directories under data/releases")
    s_rel_gc.add_argument("--dry-run", action="store_true", help="Show what would be removed without deleting")
    s_rel_gc.set_defaults(func=cmd_releases_gc)
    
    # ingest
    s_ingest = sub.add_parser("ingest", help="Import archives from data/incoming/ into releases/<ver>/archives and (optionally) extract")
    s_ingest.add_argument("--version", "-v", help="Release version to ingest into (default: active)")
    s_ingest.add_argument("--incoming", help="Override incoming directory (default: data/incoming)")
    s_ingest.add_argument("--no-extract", action="store_true", help="Do not extract after moving")
    s_ingest.set_defaults(func=cmd_ingest)

    args = p.parse_args()
    raise SystemExit(args.func(args))

if __name__ == "__main__":
    main()
