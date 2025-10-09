# src/mht/utils/booleans.py
from __future__ import annotations

_TRUES = {"1","true","yes","y","t"}
_FALSES = {"0","false","no","n","f",""}

def truthy_flag(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        s = v.strip().lower()
        if s in _TRUES:  return True
        if s in _FALSES: return False
    return False

def yesno_str(flag: bool) -> str:
    """
    Map a boolean to the canonical 'yes'/'no' string used across outputs.
    """
    return "yes" if bool(flag) else "no"
