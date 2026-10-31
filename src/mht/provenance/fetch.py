from __future__ import annotations

from dataclasses import dataclass
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Optional, Dict, Any
import requests

from mht.utils.paths import DATA_DIR
from mht.utils.logger import debug_log
from mht.utils.io import sha256_file
from mht.provenance.snaps_sources import (
    CATVER_URL,
    SUPPORT_URL,
    SnapsSource,
    resolve_snaps_source,
)
from mht.provenance.snaps_validation import validate_snaps_archive


INCOMING_DIR = DATA_DIR / "incoming"
INCOMING_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------
# Canonical HTTP helpers
# ---------------------------

def head_status(url: str, *, timeout: float = 12.0, debug: bool = False) -> Optional[int]:
    """
    Lightweight HEAD returning only the status code (or None on error).
    Used for probing release availability.
    """
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


def download_zip(url: str, dest: Path, *, timeout: float = 60.0, debug: bool = False) -> Dict[str, Any]:
    """
    Stream a ZIP to disk. Returns a dict with ok/path/size/sha256 (or error).
    """
    if debug:
        debug_log(f"[fetch] GET {url} -> {dest.as_posix()}")
    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if chunk:
                        f.write(chunk)
        info = {
            "ok": True,
            "path": dest.as_posix(),
            "size": dest.stat().st_size,
            "sha256": sha256_file(dest),
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
# Internal compatibility wrappers
# ---------------------------

# Keep these two for existing call sites inside this module; elsewhere prefer
# importing head_status/download_zip directly.
def _head(url: str, *, timeout: float = 12.0, debug: bool = False) -> Optional[int]:
    return head_status(url, timeout=timeout, debug=debug)

def _get(url: str, *, dest: Path, timeout: float = 60.0, debug: bool = False) -> Dict[str, Any]:
    return download_zip(url, dest, timeout=timeout, debug=debug)

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
    status = head_status(url, debug=debug)
    if status == 200:
        return {"url": url}
    return None

def _probe_gh(next_core: str, *, debug: bool = False) -> Optional[Dict[str, str]]:
    """
    GH keeps old revisions live; probe descending suffixes:
      'c' -> 'b' -> 'a' -> '' (no suffix).
    Stop at the first 200.
    """
    base = f"https://www.arcade-history.com/dats/history{next_core}"
    for suffix in ("c", "b", "a", ""):
        url = f"{base}{suffix}.zip"
        code = head_status(url, debug=debug)
        if code == 200:
            return {"url": url, "suffix": suffix}
    return None


def probe_snaps(
    release: str,
    *,
    timeout: float = 20.0,
    debug: bool = False,
):
    """
    Discover an advertised, release-matched SNAPS archive.

    Does not download any ZIP files. Returns None when no
    matching source is advertised or the pages cannot be read.
    """
    pages = {}

    for name, url in (
        ("support", SUPPORT_URL),
        ("catver", CATVER_URL),
    ):
        if debug:
            debug_log(f"[fetch::snaps] GET {url}")

        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            pages[name] = response.text
        except requests.RequestException as exc:
            if debug:
                debug_log(
                    f"[fetch::snaps] Failed to read {name}: {exc}"
                )
            pages[name] = ""

    return resolve_snaps_source(
        release,
        support_html=pages["support"],
        catver_html=pages["catver"],
    )


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
    next_key:    increment (-> '0282')
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

def snaps_download(
    source: SnapsSource,
    *,
    destination_dir: Path | None = None,
    overwrite: bool = False,
    debug: bool = False,
) -> Dict[str, Any]:
    """
    Download and validate a release-specific SNAPS archive.

    The destination is modified only after successful validation.
    Existing archives are preserved unless overwrite is requested.
    """
    destination_dir = Path(destination_dir or INCOMING_DIR)
    destination = destination_dir / source.filename

    if destination.exists() and not overwrite:
        try:
            provenance = validate_snaps_archive(
                destination,
                source,
            )
        except (OSError, ValueError) as exc:
            return {
                "ok": False,
                "path": destination.as_posix(),
                "reason": "invalid_existing_archive",
                "error": f"{type(exc).__name__}: {exc}",
                "note": "existing archive preserved; use overwrite to replace",
            }

        return {
            "ok": True,
            "path": destination.as_posix(),
            "reason": "exists",
            "note": "existing validated archive not overwritten",
            "size": destination.stat().st_size,
            "sha256": sha256_file(destination),
            "provenance": provenance,
        }

    try:
        with TemporaryDirectory(prefix="mht-snaps-") as temp:
            temporary = Path(temp) / source.filename

            result = download_zip(
                source.url,
                temporary,
                debug=debug,
            )

            if not result.get("ok"):
                return {
                    "ok": False,
                    "path": destination.as_posix(),
                    "error": result.get("error", "download failed"),
                }

            provenance = validate_snaps_archive(
                temporary,
                source,
            )

            destination_dir.mkdir(parents=True, exist_ok=True)
            temporary.replace(destination)

            return {
                "ok": True,
                "path": destination.as_posix(),
                "size": destination.stat().st_size,
                "sha256": sha256_file(destination),
                "note": "downloaded and validated",
                "provenance": provenance,
            }

    except (OSError, ValueError) as exc:
        return {
            "ok": False,
            "path": destination.as_posix(),
            "error": f"{type(exc).__name__}: {exc}",
        }


def mame_download(url: str, dest: Path, *, overwrite: bool = False, debug: bool = False) -> Dict[str, Any]:
    if dest.exists() and not overwrite:
        if debug:
            debug_log(f"[fetch] SKIP exists: {dest.as_posix()}")
        return {"ok": True, "path": dest.as_posix(), "reason": "exists", "note": "already in data/incoming; not re-downloaded"}
    return download_zip(url, dest, debug=debug)

def gh_download(url: str, dest: Path, *, overwrite: bool = False, debug: bool = False) -> Dict[str, Any]:
    if dest.exists() and not overwrite:
        if debug:
            debug_log(f"[fetch] SKIP exists: {dest.as_posix()}")
        return {"ok": True, "path": dest.as_posix(), "reason": "exists", "note": "already in data/incoming; not re-downloaded"}
    return download_zip(url, dest, debug=debug)

def _core_no_dot(core: str) -> str:
    # for GH naming; core like '282' already has no dot
    return core

def perform_downloads(
    plan: FetchPlan,
    *,
    ingest: bool = False,
    overwrite: bool = False,
) -> Dict[str, object]:
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    results = {"downloads": [], "skipped": [], "action": plan.action}

    # Only proceed when both are present (project policy)
    if plan.action != "both":
        results["skipped"].append("policy: not downloading unless both MAME and GH are available")
        return results

    # MAME
    mame_url  = plan.mame.get("url") or ""
    mame_name = f"mame{plan.next_key}lx.zip"
    mame_dest = INCOMING_DIR / mame_name
    if mame_dest.exists() and not overwrite:
        results["skipped"].append({
            "name": mame_name, "path": mame_dest.as_posix(),
            "reason": "exists", "note": "already in data/incoming; not re-downloaded"
        })
    else:
        r1 = mame_download(mame_url, mame_dest, overwrite=overwrite)
        results["downloads"].append({"name": mame_name, **r1})

    # GH (preserve suffix if any)
    gh_url   = plan.gh.get("url") or ""
    gh_suf   = plan.gh.get("suffix") or ""
    gh_name  = f"history{_core_no_dot(plan.next_core)}{gh_suf}.zip"
    gh_dest  = INCOMING_DIR / gh_name
    if gh_dest.exists() and not overwrite:
        results["skipped"].append({
            "name": gh_name, "path": gh_dest.as_posix(),
            "reason": "exists", "note": "already in data/incoming; not re-downloaded"
        })
    else:
        r2 = gh_download(gh_url, gh_dest, overwrite=overwrite)
        results["downloads"].append({"name": gh_name, **r2})

    if ingest:
        try:
            from mht.provenance.archives import import_incoming_archives
            _ = import_incoming_archives(incoming=INCOMING_DIR, extract=False, version=None)
            results["ingest"] = "done"
        except Exception as e:
            results["ingest"] = f"error: {e}"

    return results
