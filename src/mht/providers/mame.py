from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

USER_AGENT = "MHT/1.0 (+https://exotica.org.uk) mame-provider"
TIMEOUT = 5.0

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

def latest_for_key(key: str) -> Dict[str, Optional[str]]:
    """
    key: '0281'
    Returns:
      {
        'numeric_core': '0.281',
        'url': 'https://github.com/.../mame0281lx.zip',
        'exists': True|False
      }
    """
    core = f"{key[0]}.{key[1:]}"
    url = f"https://github.com/mamedev/mame/releases/download/mame{key}/mame{key}lx.zip"
    h = _head(url)
    return {"numeric_core": core, "url": url, "exists": bool(h.ok and h.status == 200)}

def download_zip(url: str, dest: Path) -> Dict[str, object]:
    """
    Streams to 'dest' (not overwriting by default; if exists, compares size+sha256).
    Returns: {'ok': bool, 'path': str, 'size': int, 'sha256': str, 'note': str}
    """
    # We always write to a temp then move into place, avoiding partial files.
    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    size = 0
    req = Request(url, method="GET", headers={"User-Agent": USER_AGENT})

    try:
        with urlopen(req, timeout=TIMEOUT) as resp, open(tmp, "wb") as fh:
            while True:
                chunk = resp.read(1 << 20)  # 1 MiB
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                size += len(chunk)
        sha = h.hexdigest()

        # If dest exists, compare; if the same, discard tmp.
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
