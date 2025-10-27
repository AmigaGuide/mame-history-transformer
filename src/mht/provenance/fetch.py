from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any
import hashlib
import json
import time
import requests

from mht.utils.paths import DATA_DIR
from mht.utils.logger import debug_log

INCOMING_DIR = DATA_DIR / "incoming"
INCOMING_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------
# Utilities
# ---------------------------

def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def _head(url: str, *, timeout: float = 12.0, debug: bool = False) -> Optional[int]:
    if debug:
        debug_log(f"[fetch] HEAD {url}")
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        if debug:
            debug_log(f"[fetch] ← {r.status_code} {url}")
        return r.status_code
    except Exception as e:
        if debug:
            debug_log(f"[fetch] ERROR {type(e).__name__}: {e}  ({url})")
        return None

def _get(url: str, *, dest: Path, timeout: float = 60.0, debug: bool = False) -> Dict[str, Any]:
    if debug:
        debug_log(f"[fetch] GET {url} → {dest.as_posix()}")
    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            with dest.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if chunk:
                        f.write(chunk)
        info = {
            "ok": True,
            "path": dest.as_posix(),
            "size": dest.stat().st_size,
            "sha256": _sha256_file(dest),
            "note": "downloaded",
        }
        if debug:
            debug_log(f"[fetch] OK  {url} ({info['size']} bytes)")
        return info
    except Exception as e:
        if debug:
            debug_log(f"[fetch] FAIL {type(e).__name__}: {e}  ({url})")
        return {"ok": False, "path": dest.as_posix(), "error": f"{type(e).__name__}: {e}"}

# ---------------------------
# Plan object
# ---------------------------

@dataclass
class FetchPlan:
    current_core: str          # e.g. '281' for 0.281
    next_core: str             # e.g. '282'
    next_key: str              # e.g. '0282'
    mame: Optional[Dict[str, Any]]  # {"url": ...} when available
    gh: Optional[Dict[str, Any]]    # {"url": ..., "suffix": ""|"a"|"b"|"c"} when available
    action: str                # "both" | "wait-gh" | "none"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "current_core": self.current_core,
            "next_core": self.next_core,
            "next_key": self.next_key,
            "mame": self.mame or {},
            "gh": self.gh or {},
            "action": self.action,
        }

# ---------------------------
# Providers
# ---------------------------

def _mame_url_for(key: str) -> str:
    # 'key' is like '0282'
    return f"https://github.com/mamedev/mame/releases/download/mame{key}/mame{key}lx.zip"

def _probe_mame(next_key: str, *, debug: bool = False) -> Optional[Dict[str, str]]:
    url = _mame_url_for(next_key)
    status = _head(url, debug=debug)
    if status == 200:
        return {"url": url}
    return None

def _probe_gh(next_core: str, *, debug: bool = False) -> Optional[Dict[str, str]]:
    """
    GH keeps old revisions live; probe descending suffixes:
      'c' → 'b' → 'a' → '' (no suffix).
    Stop at the first 200.
    """
    base = f"https://www.arcade-history.com/dats/history{next_core}"
    for suffix in ("c", "b", "a", ""):
        url = f"{base}{suffix}.zip"
        code = _head(url, debug=debug)
        if code == 200:
            return {"url": url, "suffix": suffix}
    return None

# ---------------------------
# Planning
# ---------------------------

def _read_current_version_key() -> Optional[str]:
    try:
        txt = (DATA_DIR / "current_version.txt").read_text(encoding="utf-8").strip()
        return txt if txt else None
    except Exception:
        return None

def _bump_core(core: str) -> str:
    # '281' -> '282'
    n = int(core)
    return f"{n+1}"

def _core_from_key(key: str) -> str:
    # '0281' -> '281'
    return key[1:]

def probe_latest(*, use_cache: bool = True, debug: bool = False) -> FetchPlan:
    """
    Decide whether MAME and GH for the *next* month are available.
    current_key: read from data/current_version.txt (e.g., '0281')
    next_key:    increment (→ '0282')
    Returns a plan with action:
      - 'both'    : MAME & GH available
      - 'wait-gh' : MAME yes, GH no
      - 'none'    : neither (or policy says do nothing)
    """
    current_key = _read_current_version_key() or "0281"
    current_core = _core_from_key(current_key)
    next_core = _bump_core(current_core)
    next_key = f"0{next_core}"

    mame = _probe_mame(next_key, debug=debug)
    gh   = _probe_gh(next_core, debug=debug)

    if mame and gh:
        action = "both"
    elif mame and not gh:
        action = "wait-gh"
    else:
        action = "none"

    return FetchPlan(
        current_core=current_core,
        next_core=next_core,
        next_key=next_key,
        mame=mame,
        gh=gh,
        action=action,
    )

# ---------------------------
# Downloads
# ---------------------------

def mame_download(url: str, dest: Path, *, overwrite: bool, debug: bool) -> Dict[str, Any]:
    if dest.exists() and not overwrite:
        if debug:
            debug_log(f"[fetch] SKIP exists: {dest.as_posix()}")
        return {"ok": True, "path": dest.as_posix(), "reason": "exists", "note": "already in data/incoming; not re-downloaded"}
    return _get(url, dest=dest, debug=debug)

def gh_download(url: str, dest: Path, *, overwrite: bool, debug: bool) -> Dict[str, Any]:
    if dest.exists() and not overwrite:
        if debug:
            debug_log(f"[fetch] SKIP exists: {dest.as_posix()}")
        return {"ok": True, "path": dest.as_posix(), "reason": "exists", "note": "already in data/incoming; not re-downloaded"}
    return _get(url, dest=dest, debug=debug)

def _core_no_dot(core: str) -> str:
    # for GH naming; core like '282' already has no dot
    return core

def perform_downloads(plan: FetchPlan, *, ingest: bool = False, overwrite: bool = False, debug: bool = False) -> Dict[str, object]:
    """
    Download the latest pair if policy allows.
    Returns {"downloads":[...], "skipped":[...], "action": plan.action}
    """
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    results: Dict[str, object] = {"downloads": [], "skipped": [], "action": plan.action}

    # Policy: only download when both are available
    if plan.action != "both":
        if debug:
            debug_log(f"[fetch] Policy prevents download (action={plan.action})")
        results["skipped"] = ["policy: not downloading unless both MAME and GH are available"]
        return results

    # MAME: stable name mame{KEY}lx.zip
    mame_url  = (plan.mame or {}).get("url") or ""
    mame_name = f"mame{plan.next_key}lx.zip"
    mame_dest = INCOMING_DIR / mame_name
    r1 = mame_download(mame_url, mame_dest, overwrite=overwrite, debug=debug)

    if r1.get("reason") == "exists":
        results["skipped"].append({"name": mame_name, **r1})
    else:
        results["downloads"].append({"name": mame_name, **r1})

    # GH: preserve suffix if present
    gh_url   = (plan.gh or {}).get("url") or ""
    gh_sfx   = (plan.gh or {}).get("suffix") or ""
    gh_name  = f"history{_core_no_dot(plan.next_core)}{gh_sfx}.zip"
    gh_dest  = INCOMING_DIR / gh_name
    r2 = gh_download(gh_url, gh_dest, overwrite=overwrite, debug=debug)

    if r2.get("reason") == "exists":
        results["skipped"].append({"name": gh_name, **r2})
    else:
        results["downloads"].append({"name": gh_name, **r2})

    # Optional auto-ingest (disabled by default)
    if ingest:
        try:
            from mht.provenance.archives import import_incoming_archives
            _ = import_incoming_archives(incoming=INCOMING_DIR, extract=False, version=None)
            results["ingest"] = "done"
        except Exception as e:
            results["ingest"] = f"error: {e}"

    return results
