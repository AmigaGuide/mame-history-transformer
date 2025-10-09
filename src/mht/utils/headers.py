"""
headers.py — build a standard summary/output header.

This keeps all artefacts consistent. It sets an ISO 8601 UTC timestamp by
default but you can override it if needed (e.g. for tests or replays).
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utc_now_iso() -> str:
    # ISO 8601 with 'Z' to mark UTC, e.g. "2025-10-01T12:34:56.789Z"
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class SummaryHeader:
    schema_id: str
    schema_version: str
    generated_at: str
    versions: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "versions": self.versions,
        }


def build_summary_header(
    schema_id: str,
    schema_version: str,
    versions: Dict[str, Any],
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:       
    """
    Create the standard header block shared by all summary JSONs.

    Returns
    -------
    dict
        {
          "schema_id": ...,
          "schema_version": ...,
          "generated_at": "<UTC ISO8601>Z",
          "versions": {...}
        }
    """
    header = SummaryHeader(
        schema_id=schema_id,
        schema_version=schema_version,
        generated_at=generated_at or _utc_now_iso(),
        versions=versions,
    )
    return header.to_dict()
