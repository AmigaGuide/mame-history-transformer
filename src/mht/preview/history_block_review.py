"""Read-only presentation of already-retained GH Trivia block provenance.

Detector names and policy flags are not findings of an error. Source-line
positions are 1-based; filtered-line positions are 0-based as stored.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

MAX_DETAIL_BLOCKS = 60
MAX_PREVIEW_CHARS = 180


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _preview(block: dict) -> str:
    kind = block.get("type")
    if kind in ("bullet_list", "numbered_list"):
        values = block.get("items")
        raw = " | ".join(v for v in values if isinstance(v, str)) if isinstance(values, list) else ""
    elif kind == "pair":
        raw = f"{block.get('label', '')}: {block.get('value', '')}"
    else:
        raw = block.get("text") if isinstance(block.get("text"), str) else ""
    return raw[:MAX_PREVIEW_CHARS] + ("..." if len(raw) > MAX_PREVIEW_CHARS else "")


def _int_or_none(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def build_machine_block_review(trivia: Any) -> dict:
    """Summarise every recorded block; show bounded provenance detail.

    No detector is interpreted as an error. The detailed records are sampled
    in source section/block order, with the number omitted disclosed.
    """
    sections = _mapping(_mapping(trivia).get("sections"))
    totals = Counter()
    detector_counts = Counter()
    rows = []
    count = 0
    sections_seen = []
    heuristic_blocks = 0
    suppress_marked_blocks = 0
    missing_meta = 0

    for section, record in sections.items():
        if not isinstance(section, str):
            continue
        blocks = _mapping(record).get("blocks")
        if not isinstance(blocks, list):
            continue
        section_count = 0
        for idx, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            count += 1
            section_count += 1
            kind = block.get("type")
            kind = kind if isinstance(kind, str) else "unknown"
            totals[kind] += 1
            meta = _mapping(block.get("meta"))
            if not meta:
                missing_meta += 1
            policy = _mapping(meta.get("policy"))
            heuristic = policy.get("heuristic_per_line") is True
            if heuristic:
                heuristic_blocks += 1
            suppressions = meta.get("suppressions")
            suppressions = [x for x in suppressions if isinstance(x, str)] if isinstance(suppressions, list) else []
            if suppressions:
                suppress_marked_blocks += 1
            detectors = meta.get("detectors")
            detectors = [x for x in detectors if isinstance(x, str)] if isinstance(detectors, list) else []
            detector_counts.update(detectors)
            if len(rows) < MAX_DETAIL_BLOCKS:
                rows.append({
                    "section": section, "index": _int_or_none(meta.get("block_index")),
                    "fallback_index": idx, "kind": kind, "text": _preview(block),
                    "detectors": detectors, "per_line": policy.get("per_line") is True,
                    "heuristic": heuristic, "suppressions": suppressions,
                    "raw_start": _int_or_none(meta.get("raw_line_start")),
                    "raw_end": _int_or_none(meta.get("raw_line_end")),
                    "filtered_start": _int_or_none(meta.get("filtered_line_start")),
                    "filtered_end": _int_or_none(meta.get("filtered_line_end")),
                    "text_hash": meta.get("text_hash") if isinstance(meta.get("text_hash"), str) else None,
                })
        if section_count:
            sections_seen.append({"name": section, "count": section_count})

    return {
        "has_evidence": count > 0,
        "count": count, "sections": sections_seen,
        "kinds": sorted(totals.items(), key=lambda x: (-x[1], x[0])),
        "detectors": sorted(detector_counts.items(), key=lambda x: (-x[1], x[0])),
        "heuristic_blocks": heuristic_blocks,
        "suppression_marked_blocks": suppress_marked_blocks,
        "missing_meta": missing_meta,
        "rows": rows, "omitted": max(0, count - len(rows)),
    }


def build_history_policy_review(summary: Any) -> dict:
    """Aggregate per-section invocation counts, not block or game counts."""
    qc = _mapping(_mapping(summary).get("provenance_qc"))
    policies = _mapping(qc.get("policy_counts"))
    rows = []
    for section, value in sorted(policies.items()):
        if not isinstance(section, str) or not isinstance(value, dict):
            continue
        per_line = _int_or_none(value.get("per_line"))
        heuristic = _int_or_none(value.get("heuristic_per_line"))
        if per_line is not None or heuristic is not None:
            rows.append({"section": section, "per_line": per_line, "heuristic": heuristic})
    return {"rows": rows, "blocks_with_suppressions": _int_or_none(qc.get("blocks_with_suppressions"))}
