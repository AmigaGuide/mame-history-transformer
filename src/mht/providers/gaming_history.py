from __future__ import annotations

import string
import time
from dataclasses import dataclass
from typing import Dict, Optional, List

from mht.provenance.fetch import head_status as _head


USER_AGENT = "MHT/1.0 (+https://exotica.org.uk) gh-provider"
TIMEOUT = 5.0
SLEEP_BETWEEN_PROBES = 0.2   # seconds
MAX_SUFFIX = "c"             # fixed cap by project policy

@dataclass
class HeadResult:
    url: str
    ok: bool
    status: int


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
