from __future__ import annotations

import hashlib
import string
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, List
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

USER_AGENT = "MHT/1.0 (+https://exotica.org.uk) gh-provider"
TIMEOUT = 5.0
SLEEP_BETWEEN_PROBES = 0.2   # seconds
MAX_SUFFIX = "c"             # fixed cap by project policy

@dataclass
class HeadResult:
    url: str
    ok: bool
    status: int

def _head(url: str, *, timeout: float = TIMEOUT) -> HeadResult:
    req = Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return HeadResult(url, True, getattr(resp, "status", 200))
    except HTTPError as e:
        return HeadResult(url, False, e.code)
    except URLError:
        return HeadResult(url, False, 0)

def _suffix_order(max_suffix: str = MAX_SUFFIX) -> List[str]:
    # Reverse from max down to 'a', then no suffix
    max_suffix = (max_suffix or "c").lower()
    letters = [ch for ch in string.ascii_lowercase if ch <= max_suffix]
    letters.reverse()
    return letters + [""]

def latest_for_core(core_no_dot: str) -> Dict[str, Optional[str]]:
    """
    core_no_dot: '281'
    Tries history{core}{suffix}.zip for suffix in ['c','b','a',''].
    Returns:
      {
        'numeric_core': '2.81',
        'suffix': '', 'a', 'b', 'c' (or None if none found),
        'url': 'https://.../history281.zip' (or last tried),
        'exists': True|False
      }
    """
    core_float = f"{int(core_no_dot[0])}.{core_no_dot[1:]}" if len(core_no_dot) >= 2 else core_no_dot
    tried_url = None
    for suf in _suffix_order():
        fname = f"history{core_no_dot}{suf}.zip"
        url = f"https://www.arcade-history.com/dats/{fname}"
        tried_url = url
        h = _head(url)
        if h.ok and h.status == 200:
            return {"numeric_core": core_float, "suffix": suf, "url": url, "exists": True}
        time.sleep(SLEEP_BETWEEN_PROBES)
    return {"numeric_core": core_float, "suffix": None, "url": tried_url, "exists": False}

def download_zip(url: str, dest: Path) -> Dict[str, object]:
    # Same implementation idea as MAME provider
    import hashlib
    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    size = 0
    req = Request(url, method="GET", headers={"User-Agent": USER_AGENT})

    try:
        with urlopen(req, timeout=TIMEOUT) as resp, open(tmp, "wb") as fh:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                size += len(chunk)
        sha = h.hexdigest()

        if dest.exists():
            try:
                from hashlib import file_digest
                with open(dest, "rb") as f:
                    sha_existing = file_digest(f, "sha256").hexdigest()
                if sha_existing == sha:
                    tmp.unlink(missing_ok=True)
                    return {"ok": True, "path": dest.as_posix(), "size": dest.stat().st_size, "sha256": sha, "note": "already present"}
            except Exception:
                pass

        tmp.replace(dest)
        return {"ok": True, "path": dest.as_posix(), "size": size, "sha256": sha, "note": "downloaded"}

    except Exception as e:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return {"ok": False, "path": dest.as_posix(), "size": 0, "sha256": "", "note": f"error: {e}"}
