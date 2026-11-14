"""Stage-specific encoding dependencies with conservative legacy stamp compatibility.

The canonical encoding cache remains a single encodings.json. These functions
are read-only and do not create additional metadata files.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_LEAVES = {
    "mht.stage.mame": ("mame.xml",),
    "mht.stage.history": ("history.xml",),
    "mht.stage.ini": (
        "[GAMING HISTORY] Game Or No Game.ini",
        "[GAMING HISTORY] Machine Category.ini",
        "[GAMING HISTORY] Machine Type.ini",
    ),
}
_FIELDS = ("encoding", "zip_archive", "zip_member", "zip_crc32", "zip_size_bytes")


def _selected_record(record: Any) -> dict | None:
    if not isinstance(record, dict):
        return None
    if not isinstance(record.get("encoding"), str) or not record["encoding"].strip():
        return None
    if not isinstance(record.get("zip_archive"), str) or not record["zip_archive"]:
        return None
    if not isinstance(record.get("zip_member"), str) or not record["zip_member"]:
        return None
    if not isinstance(record.get("zip_crc32"), int) or not isinstance(record.get("zip_size_bytes"), int):
        return None
    return {key: record[key] for key in _FIELDS}


def _selected_cache(stage_id: str, cache_path: Path) -> dict | None:
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    selected = {}
    for leaf in _LEAVES[stage_id]:
        if leaf not in data:
            if stage_id == "mht.stage.ini":
                selected[leaf] = None  # optional upstream INI
                continue
            return None
        selected[leaf] = _selected_record(data[leaf])
        if selected[leaf] is None:
            return None
    return selected


def semantic_cache_signature(stage_id: str, path: Path) -> str | None:
    """Return a per-stage stable digest for encodings.json or None for other inputs.

    A missing/invalid cache produces a sentinel digest, never a default UTF-8
    record or a false match to a populated cache.
    """
    if stage_id not in _LEAVES or path.name.lower() != "encodings.json":
        return None
    chosen = _selected_cache(stage_id, path)
    if chosen is None:
        # Fail closed, including if the file exists but cannot be decoded.
        return "invalid-cache"
    canonical = json.dumps(chosen, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def legacy_stage_compatible(previous: dict, current: dict, inputs: list[Path]) -> bool:
    """Accept a legacy stamp only when all stage-specific evidence agrees.

    Existing old stamps hashed the *entire* encoding cache. A changed cache
    mtime alone should not invalidate MAME if its own archive, tool version,
    outputs and recorded encoding provenance are all unchanged.

    Missing legacy provenance fails closed, so compatibility cannot silently
    certify a stamp that predates reliable source metadata.
    """
    stage_id = current.get("stage_id")
    if stage_id not in _LEAVES:
        return False
    if previous.get("stage_id") != stage_id or previous.get("tool_version") != current.get("tool_version"):
        return False
    # Verify the prior stamp was actually created from its saved file signatures.
    # An arbitrary/malformed old digest must not be migrated to a fresh state.
    old_inputs_for_digest = previous.get("inputs")
    if not isinstance(old_inputs_for_digest, list):
        return False
    try:
        prior_basis = {
            "stage_id": previous["stage_id"],
            "tool_version": previous["tool_version"],
            "inputs": [
                {"path": item["path"], "size": item["size"], "mtime_ns": item["mtime_ns"]}
                for item in old_inputs_for_digest
            ],
            "extra": previous.get("extra"),
        }
        prior_digest = hashlib.sha256(json.dumps(
            prior_basis, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")).hexdigest()
    except (KeyError, TypeError, ValueError):
        return False
    if previous.get("digest") != prior_digest:
        return False
    old_inputs, now_inputs = previous.get("inputs"), current.get("inputs")
    if not isinstance(old_inputs, list) or not isinstance(now_inputs, list):
        return False
    if len(old_inputs) != len(now_inputs) or len(inputs) != len(now_inputs):
        return False
    seen_cache = False
    for old, now, path in zip(old_inputs, now_inputs, inputs):
        if not isinstance(old, dict) or not isinstance(now, dict) or old.get("path") != now.get("path"):
            return False
        if path.name.lower() == "encodings.json":
            seen_cache = True
        elif any(old.get(k) != now.get(k) for k in ("size", "mtime_ns")):
            return False
    if not seen_cache:
        return False
    cache_path = next(p for p in inputs if p.name.lower() == "encodings.json")
    chosen = _selected_cache(stage_id, cache_path)
    if chosen is None:
        return False
    details = previous.get("inputs_detail")
    if not isinstance(details, list):
        return False
    old_by_leaf = {item.get("leaf"): item for item in details if isinstance(item, dict)}
    for leaf, rec in chosen.items():
        old = old_by_leaf.get(leaf)
        if rec is None:
            if old and old.get("zip_member"):
                return False
            continue
        if not isinstance(old, dict) or any(old.get(k) != rec[k] for k in _FIELDS):
            return False
    # Require prior ZIP-member signatures to agree with the selected source
    # file itself, not just the cache's self-reported values.
    try:
        import zipfile
        source = next(p for p in inputs if p.name.lower() != "encodings.json")
        with zipfile.ZipFile(source) as zf:
            by_name = {info.filename: info for info in zf.infolist()}
            for record in chosen.values():
                if record is None:
                    continue
                info = by_name.get(record["zip_member"])
                if (record["zip_archive"] != source.name or info is None
                    or record["zip_crc32"] != info.CRC or record["zip_size_bytes"] != info.file_size):
                    return False
    except (OSError, ValueError, zipfile.BadZipFile, StopIteration):
        return False
    return True
