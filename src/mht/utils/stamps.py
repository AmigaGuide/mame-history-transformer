from __future__ import annotations

import json, os, tempfile, hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Dict, Any, Tuple
from datetime import datetime, timezone


from mht.utils.paths import STAMPS_DIR
from mht.utils.versions import tool_version


# Canonical dump (used for digest)
def _canon(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

# Human-friendly dump (preserve insertion order; do NOT sort)
def _pretty(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=False, indent=2)

def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(path.parent)) as tmp:
        tmp.write(text)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)

@dataclass(frozen=True)
class FileSig:
    path: str
    size: int
    mtime_ns: int

def _size_human(n: int) -> str:
    if n is None or n < 0:
        return "unknown"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    i = 0
    x = float(n)
    while x >= 1024.0 and i < len(units) - 1:
        x /= 1024.0
        i += 1
    return f"{x:.1f} {units[i]}"

def file_signatures(paths: Iterable[Path]) -> list[Dict[str, Any]]:
    sigs: list[Dict[str, Any]] = []
    for p in paths:
        try:
            st = p.stat()
            mtime = st.st_mtime
            sigs.append({
                "path": p.as_posix(),
                "size": st.st_size,
                "size_h": _size_human(st.st_size),
                "mtime_ns": st.st_mtime_ns,
                "mtime_iso": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            })
        except FileNotFoundError:
            sigs.append({
                "path": p.as_posix(),
                "size": -1,
                "size_h": "unknown",
                "mtime_ns": -1,
                "mtime_iso": None,
            })
    return sigs

def make_stamp(schema_id: str, tool_version: str, inputs: Iterable[Path], extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    inputs_list = file_signatures(inputs)
    payload = {
        "schema_id": "mht.stage.stamp",
        "schema_version": "1.0.0",
        "generated_at": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
        "stage_id": schema_id,            # e.g. "mht.stage.ini" or "mht.stage.transform"
        "tool_version": tool_version,     # from versions.py
        "inputs": inputs_list,            # human-friendly view
    }
    if extra:
        payload["extra"] = extra

    # Build digest from canonical fields only (stable, compact)
    minimal_inputs = [
        {"path": it["path"], "size": it["size"], "mtime_ns": it["mtime_ns"]}
        for it in inputs_list
    ]
    digest_basis = {
        "stage_id": payload["stage_id"],
        "tool_version": payload["tool_version"],
        "inputs": minimal_inputs,
        "extra": payload.get("extra"),
    }
    payload["digest"] = hashlib.sha256(_canon(digest_basis).encode("utf-8")).hexdigest()
    return payload

def load_stamp(path: Path) -> Dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save_stamp(path: Path, stamp: Dict[str, Any]) -> None:
    _atomic_write(path, _pretty(stamp))  # now preserves build structure

def is_fresh(current: Dict[str, Any], previous: Dict[str, Any] | None) -> bool:
    if not previous or not isinstance(previous, dict):
        return False
    return previous.get("digest") == current.get("digest")

def stage_is_fresh(
    stamp_filename: str,
    *,
    schema_id: str,
    tool: str,
    inputs: Iterable[Path],
) -> Tuple[bool, Path, dict]:
    """
    Convenience wrapper for stage stamps:
    - Ensures STAMPS_DIR exists.
    - Builds the current stamp (including tool version and inputs).
    - Loads the previous stamp and checks freshness.

    Returns
    -------
    (is_fresh, stamp_path, current_stamp_dict)
    """
    STAMPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp_path = STAMPS_DIR / stamp_filename
    current = make_stamp(
        schema_id=schema_id,
        tool_version=tool_version(tool),
        inputs=list(inputs),
    )
    prev = load_stamp(stamp_path)
    return is_fresh(current, prev), stamp_path, current
