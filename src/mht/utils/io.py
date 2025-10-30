"""
io.py — deterministic JSON writing helpers and canonical file metadata/hashing.
"""

from __future__ import annotations

import json
import os
import hashlib
import datetime
from pathlib import Path
from typing import Any, Dict

from mht.utils.config import LOG_LEVEL
from mht.utils.logger import setup_logger

log = setup_logger(log_level=LOG_LEVEL)


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
    - sorted keys for stable diffs (toggle with sort_keys)
    - 2-space indent, Unix newlines
    Returns True on success; raises on failure.
    """
    text = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=sort_keys)
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


def sha256_file(p: Path, *, chunk_size: int = 65536) -> str:
    """
    Return the hex SHA-256 of file `p`. Chunked to avoid high RAM usage.
    """
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def file_meta(p: Path, *, include_hash: bool = True) -> Dict[str, Any]:
    """
    Stable, deterministic file metadata used in manifests and summaries.
    Returns:
        {
          "path": p.as_posix(),
          "size_bytes": <int>,
          "modified_utc": "<ISO8601>Z",
          "sha256": "<hex>"  # omitted if include_hash=False
        }
    """
    st = p.stat()
    meta: Dict[str, Any] = {
        "path": p.as_posix(),
        "size_bytes": int(st.st_size),
        "modified_utc": datetime.datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z",
    }
    if include_hash:
        meta["sha256"] = sha256_file(p)
    return meta


# --- Backwards-compat aliases (safe to keep until callers are updated) ---
_sha256_file = sha256_file
_file_meta = file_meta
