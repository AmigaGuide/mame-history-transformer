"""Read-only diagnostics derived from existing MHT processing summaries.

These records are observations reported by source parsers and the transformer.
They are not inferred errors and do not determine publication eligibility.
"""
from __future__ import annotations

from typing import Any

from .preview_data import PreviewData


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _non_negative_count(value: Any) -> int | None:
    # A missing count is not the same as a reported zero.
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _examples(value: Any, *, limit: int = 5) -> list[str]:
    """Return a compact, readable sample, without altering the source records."""
    if isinstance(value, dict):
        return [str(k) for k in list(value)[:limit]]
    if isinstance(value, list):
        samples: list[str] = []
        for item in value[:limit]:
            if isinstance(item, dict):
                machine = item.get("machine") or item.get("system") or item.get("name")
                samples.append(str(machine) if machine else str(item))
            else:
                samples.append(str(item))
        return samples
    return []


def build_diagnostic_groups(data: PreviewData) -> list[dict]:
    """Prepare summary-backed findings for the Flask diagnostics overview.

    Each row documents its originating summary path and avoids extrapolating
    from an absent field. Zero is shown only when actually recorded.
    """
    groups: list[dict] = []

    def group(title: str, endpoint: str) -> dict:
        result = {"title": title, "summary_endpoint": endpoint, "findings": []}
        groups.append(result)
        return result

    def add(target: dict, label: str, value: Any, path: str, explanation: str, sample: Any = None) -> None:
        count = _non_negative_count(value)
        if count is None:
            return
        target["findings"].append({
            "label": label,
            "count": count,
            "path": path,
            "explanation": explanation,
            "examples": _examples(sample),
        })

    mame = group("MAME parser", "summary_mame")
    drops = _mapping(_mapping(data.mame_summary.get("totals")).get("invalid_displays_dropped"))
    add(mame, "Invalid display records dropped", drops.get("count"),
        "totals.invalid_displays_dropped", "The parser rejected display records that failed its checks.",
        drops.get("examples"))

    history = group("Gaming History parser", "summary_history")
    anomalies = _mapping(data.history_summary.get("anomalies"))
    residue = _mapping(data.history_summary.get("residue_flags"))
    headings = _mapping(data.history_summary.get("headings_qc"))
    for label, source, key, explanation in (
        ("Odd numbers of quotation marks", anomalies, "odd_number_of_quotes", "Source lines flagged for quotation-mark review."),
        ("Odd numbers of brackets", anomalies, "odd_number_of_brackets", "Source lines flagged for bracket review."),
        ("PORTS sections missing subheadings", anomalies, "ports_missing_subheadings", "Structure warrants review; ports are not automatically invalid."),
        ("Unparseable dates", residue, "unparsable_dates", "Dates that the parser could not interpret."),
    ):
        entry = _mapping(source.get(key))
        add(history, label, entry.get("count"),
            ("residue_flags" if source is residue else "anomalies") + "." + key,
            explanation, entry.get("by_system"))

    unmapped = _mapping(headings.get("unmapped_headings"))
    if "unmapped_headings" in headings:
        add(history, "Unmapped section headings", len(unmapped), "headings_qc.unmapped_headings",
            "Distinct non-standard headings without a recognised mapping (not a count of affected systems).",
            unmapped)
    near_miss = _mapping(headings.get("near_miss_banners"))
    add(history, "Systems with near-miss PORTS banners", near_miss.get("systems_affected"),
        "headings_qc.near_miss_banners.systems_affected",
        "Systems with potentially unusual banner spacing.", near_miss.get("by_system"))

    ini = group("Gaming History INI coverage", "summary_ini")
    totals = _mapping(data.ini_summary.get("totals"))
    for label, key in (
        ("Missing game-status classification", "missing_in_game_status"),
        ("Missing category classification", "missing_in_category"),
        ("Missing type classification", "missing_in_type"),
    ):
        add(ini, label, totals.get(key), "totals." + key,
            "Count relative to the union of machine names across the three INI files; not necessarily a parsing error.")

    transform = group("Transformation", "summary_transform")
    counts = _mapping(data.transform_summary.get("counts"))
    audio = _mapping(counts.get("audio"))
    add(transform, "Audio channel/speaker mismatches", audio.get("channel_speaker_mismatches"),
        "counts.audio.channel_speaker_mismatches", "Records flagged by the transform's audio comparison.",
        audio.get("mismatch_examples"))
    errors = data.transform_summary.get("errors")
    if isinstance(errors, list):
        add(transform, "Recorded transformation errors", len(errors), "errors",
            "Entries explicitly recorded as errors by the transformer.", errors)
    title_counts = _mapping(data.transform_summary.get("title_anomaly_counts"))
    if "title_anomaly_counts" in data.transform_summary:
        add(transform, "Title anomalies (reported instances)",
            sum(v for v in title_counts.values() if isinstance(v, int) and not isinstance(v, bool) and v > 0),
            "title_anomaly_counts", "Sum of existing title-anomaly category counts; categories may overlap.",
            title_counts)

    return groups
