"""
io.py — deterministic JSON writing helpers.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any

from mht.utils.logger import debug_log

def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """
    Write text atomically to avoid partial files if the process is interrupted.
    Creates parent directories if needed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(text, encoding=encoding, newline="\n")
    os.replace(tmp_path, path)  # atomic on POSIX/Windows for same filesystem


def write_json(path: Path, obj: Any, *, sort_keys: bool = True) -> bool:
    """
    Write JSON deterministically:
    - UTF-8, no ASCII escaping
    - sorted keys for stable diffs
    - 2-space indent, Unix newlines
    Returns True on success; raises on failure.
    """
    text = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=sort_keys)
    #text = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)
    # Ensure trailing newline for POSIX-friendly diffs
    if not text.endswith("\n"):
        text += "\n"
    _atomic_write_text(Path(path), text, encoding="utf-8")
    return True

def read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error(f"Failed to read {path}: {e}")
        return None
