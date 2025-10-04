from __future__ import annotations

def truthy_flag(v) -> bool:
    """Lenient truthiness for flags coming from XML/INI (0/1, yes/no, true/false, etc.)."""
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"1", "true", "yes", "y", "t"}:
            return True
        if s in {"0", "false", "no", "n", "f", ""}:
            return False
    return False
