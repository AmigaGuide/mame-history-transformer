from __future__ import annotations

"""
Low-level formatting and type-shaping helpers for preview templates.

These are intentionally boring utility functions that keep templates simple and
keep route handlers readable.
"""

import json
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime, timezone

from .preview_data import JsonDict


def as_dict(obj: Any) -> JsonDict:
    """Return obj if it is a dict; otherwise return an empty dict."""
    return obj if isinstance(obj, dict) else {}


def as_list(obj: Any) -> List[Any]:
    """Return obj if it is a list; otherwise return an empty list."""
    return obj if isinstance(obj, list) else []


def pretty_json(doc: JsonDict) -> str:
    """Render a dict as human-readable JSON for template display."""
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=False)


def sorted_pairs_from_mapping(mapping: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """
    Sort mapping by numeric value descending if possible; otherwise by key.

    Returns:
        List of (key, value) tuples.
    """
    pairs = list(mapping.items())
    try:
        pairs.sort(key=lambda kv: (kv[1] if isinstance(kv[1], (int, float)) else -1), reverse=True)
        return pairs
    except Exception:  # noqa: BLE001
        return sorted(pairs, key=lambda kv: str(kv[0]))


def top_n_from_mapping(mapping: Dict[str, Any], n: int = 5) -> List[str]:
    """Return human-readable 'key: value' strings for the top-N entries in mapping."""
    pairs = sorted_pairs_from_mapping(mapping)
    return [f"{k}: {v}" for k, v in pairs[:n]]


def overview_headlines(labels_and_values: List[Tuple[str, Any]]) -> List[JsonDict]:
    """Convert (label, value) pairs into a template-friendly list of dicts."""
    return [{"label": label, "value": value} for label, value in labels_and_values]


def header_versions(summary: JsonDict) -> JsonDict:
    """
    Return summary['header']['versions'] as a dict, or {} if missing.
    """
    header = as_dict(summary.get("header"))
    return as_dict(header.get("versions"))

def format_utc_iso(ts: object) -> Optional[str]:
    """
    Format an ISO-8601 UTC timestamp into a more readable string.

    Accepts strings like:
        2026-01-17T14:56:26.730236Z
        2026-01-17T14:56:26Z

    Returns:
        "17 Jan 2026, 14:56:26 UTC" or None if ts is not usable.
    """
    if not isinstance(ts, str):
        return None

    s = ts.strip()
    if not s:
        return None

    # Handle Zulu suffix used by our summaries.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return ts  # fall back to original string if parsing fails

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    return dt.strftime("%d %b %Y, %H:%M:%S UTC")


def format_duration_seconds(value: object) -> Optional[str]:
    """
    Format a duration value (seconds) into a friendly string.

    Returns:
        "12.0 seconds" or None if value is not usable.
    """
    if value is None:
        return None

    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return str(value)

    return f"{seconds:.1f} seconds"
