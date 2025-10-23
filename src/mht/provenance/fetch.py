from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from mht.utils.paths import DATA_DIR
from mht.providers.mame import latest_for_key as mame_latest, download_zip as mame_download
from mht.providers.gaming_history import latest_for_core as gh_latest, download_zip as gh_download

CACHE_PATH = DATA_DIR / "providers_cache.json"
INCOMING_DIR = DATA_DIR / "incoming"

@dataclass
class FetchPlan:
    current_core: str      # '0.280'
    next_key: str          # '0281'
    next_core: str         # '0.281'
    mame: Dict[str, object]
    gh: Dict[str, object]
    action: str            # 'none'|'wait-gh'|'both'

def _read_current_core() -> str:
    fp = DATA_DIR / "current_version.txt"
    return (fp.read_text(encoding="utf-8").strip() if fp.exists() else "0.000")

def _bump_core(core: str) -> Tuple[str, str]:
    """'0.280' -> ('0281','0.281')  returns (key, dotted)"""
    core = core.strip()
    if core.startswith("0.") and core[2:].isdigit():
        n = int(core[2:])
        nxt = n + 1
        return (f"0{nxt:03d}", f"0.{nxt:03d}")
    # Fallback, try to parse the last numeric chunk
    try:
        parts = core.split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        dotted = ".".join(parts)
        digits = "".join(ch for ch in dotted if ch.isdigit())
        return (digits.zfill(4), dotted)
    except Exception:
        return ("0001", "0.001")

def _core_no_dot(core: str) -> str:
    # '0.281' -> '281'
    return core.replace(".", "")

def _read_cache() -> Dict[str, object]:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _write_cache(doc: Dict[str, object]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

def probe_latest(use_cache: bool = True) -> FetchPlan:
    cur = _read_current_core()
    next_key, next_core = _bump_core(cur)

    m = mame_latest(next_key)
    g = gh_latest(_core_no_dot(next_core))

    # Cache last check (purely informational for now)
    cache = _read_cache()
    cache.update({"last_probe": {"current": cur, "next_core": next_core, "mame": m, "gh": g}})
    _write_cache(cache)

    if m.get("exists") and g.get("exists"):
        action = "both"
    elif m.get("exists") and not g.get("exists"):
        action = "wait-gh"
    else:
        action = "none"

    return FetchPlan(current_core=cur, next_key=next_key, next_core=next_core, mame=m, gh=g, action=action)

def perform_downloads(plan: FetchPlan, *, ingest: bool = False, overwrite: bool = False) -> Dict[str, object]:
    """
    Execute a download plan produced by probe_latest().
    - Only downloads when policy says action == 'both' (MAME and GH available).
    - Writes into data/incoming/ (INCOMING_DIR).
    - Skips re-downloads if the exact target filename already exists, unless overwrite=True.
    - Optionally ingests into releases/<ver>/archives after downloading (or skipping).

    Returns:
      {
        "downloads": [ { "name": ..., "ok": bool, "path": ..., "size": int, "sha256": str, "note": "downloaded" }, ... ],
        "skipped":   [ { "name": ..., "path": ..., "reason": "exists", "note": "..."} , ... ],
        "action":    plan.action,   # e.g. "both" | "mame_only" | "none"
        "ingest":    "done" | "error: ..."   # present only if ingest=True
      }
    """
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    results: Dict[str, object] = {"downloads": [], "skipped": [], "action": plan.action}

    # Project policy: only proceed when BOTH are available
    if plan.action != "both":
        results["skipped"] = ["policy: not downloading unless both MAME and GH are available"]
        return results

    # --- MAME ---
    mame_url = plan.mame.get("url") or ""
    mame_name = f"mame{plan.next_key}lx.zip"
    mame_dest = INCOMING_DIR / mame_name

    if mame_dest.exists() and not overwrite:
        results["skipped"].append({
            "name": mame_name,
            "path": mame_dest.as_posix(),
            "reason": "exists",
            "note": "already in data/incoming; not re-downloaded",
        })
    else:
        r1 = mame_download(mame_url, mame_dest)
        # r1 is expected to include ok/path/size/sha256/note
        results["downloads"].append({"name": mame_name, **r1})

    # --- GH (preserve possible suffix like 'a', 'b', 'c') ---
    gh_url = plan.gh.get("url") or ""
    gh_suffix = plan.gh.get("suffix") or ""            # "", "a", "b", "c"
    gh_name = f"history{_core_no_dot(plan.next_core)}{gh_suffix}.zip"
    gh_dest = INCOMING_DIR / gh_name

    if gh_dest.exists() and not overwrite:
        results["skipped"].append({
            "name": gh_name,
            "path": gh_dest.as_posix(),
            "reason": "exists",
            "note": "already in data/incoming; not re-downloaded",
        })
    else:
        r2 = gh_download(gh_url, gh_dest)
        results["downloads"].append({"name": gh_name, **r2})

    # Optional: ingest after download/skip
    if ingest:
        try:
            from mht.provenance.archives import import_incoming_archives
            # In ZIP-first world, extraction is optional; keep True to populate extracted/ for convenience
            _ = import_incoming_archives(incoming=INCOMING_DIR, extract=True)
            results["ingest"] = "done"
        except Exception as e:
            results["ingest"] = f"error: {e}"

    return results
