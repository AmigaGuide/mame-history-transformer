from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from mht.provenance.fetch import head_status as _head


USER_AGENT = "MHT/1.0 (+https://exotica.org.uk) mame-provider"
TIMEOUT = 5.0

@dataclass
class HeadResult:
    url: str
    ok: bool
    status: int


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
