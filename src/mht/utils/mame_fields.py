from __future__ import annotations

from typing import Optional

def normalise_year(value: str | None) -> Optional[str]:
    """
    Keep the MAME 'year' as a trimmed string (it can be '1985', '1985?', '199X', etc.).
    Return None if empty.
    """
    v = (value or "").strip()
    return v or None

def normalise_manufacturer(value: str | None) -> Optional[str]:
    """
    Store the raw manufacturer as-trimmed (display formatting happens later).
    Return None if empty.
    """
    v = (value or "").strip()
    return v or None
