"""Read-only diagnostics based on recorded MHT stage summaries.

Findings are observations, not inferred defects, and never affect publication.
Only known preview machine shortnames become links; a heading or category label
is not treated as a machine merely because it happens to match one.
"""
from __future__ import annotations

from typing import Any

from .preview_data import PreviewData

SAMPLE_LIMIT = 5


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _non_negative_count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _examples(value: Any, *, limit: int = SAMPLE_LIMIT) -> list[str]:
    """Produce readable example identifiers, never a Python dict repr."""
    if isinstance(value, dict):
        items = value.keys()
    elif isinstance(value, list):
        items = value
    else:
        return []
    examples: list[str] = []
    for item in items:
        if len(examples) >= limit:
            break
        if isinstance(item, dict):
            item = item.get("machine") or item.get("system") or item.get("name")
        if isinstance(item, str) and item.strip():
            examples.append(item.strip())
    return examples


def build_diagnostic_groups(data: PreviewData) -> list[dict]:
    """Prepare bounded, source-backed findings and safe preview links.

    The count always retains its source meaning. An affected-system count is
    shown separately only when the summary explicitly supplies one.
    """
    available = set(data.machine_order)
    groups: list[dict] = []

    def group(title: str, endpoint: str, stage: str, filename: str) -> dict:
        result = {"title": title, "summary_endpoint": endpoint,
                  "stage": stage, "filename": filename, "findings": []}
        groups.append(result)
        return result

    def add(target: dict, label: str, value: Any, path: str, explanation: str,
            sample: Any = None, *, affected: Any = None,
            count_label: str = "Recorded count", machine_examples: bool = True) -> None:
        count = _non_negative_count(value)
        if count is None:
            return
        names = _examples(sample)
        target["findings"].append({
            "label": label, "count": count, "count_label": count_label,
            "systems_affected": _non_negative_count(affected),
            "path": path, "explanation": explanation, "examples": names,
            "example_items": [
                {"name": name, "machine": name if machine_examples and name in available else None}
                for name in names
            ],
        })

    mame = group("MAME parser", "summary_mame", "mame", "mame_parsing_summary.json")
    mame_totals = _mapping(data.mame_summary.get("totals"))
    drops = _mapping(mame_totals.get("invalid_displays_dropped"))
    path = "totals.invalid_displays_dropped"
    if not drops:
        drops = _mapping(_mapping(data.mame_summary.get("anomalies")).get("dropped_displays"))
        path = "anomalies.dropped_displays"
    add(mame, "Invalid display records dropped", drops.get("count"), path,
        "Display records rejected by the parser's validation checks.", drops.get("examples"),
        count_label="Dropped records")

    history = group("Gaming History parser", "summary_history", "history", "history_parsing_summary.json")
    anomalies = _mapping(data.history_summary.get("anomalies"))
    residue = _mapping(data.history_summary.get("residue_flags"))
    headings = _mapping(data.history_summary.get("headings_qc"))
    for label, source, key, explanation in (
        ("Odd numbers of quotation marks", anomalies, "odd_number_of_quotes",
         "Source lines flagged for quotation-mark review."),
        ("Odd numbers of brackets", anomalies, "odd_number_of_brackets",
         "Source lines flagged for bracket review."),
        ("PORTS sections missing subheadings", anomalies, "ports_missing_subheadings",
         "PORTS structure warrants review; the records are not automatically invalid."),
        ("Unparseable dates", residue, "unparsable_dates",
         "Dates the parser could not interpret."),
    ):
        entry = _mapping(source.get(key))
        source_prefix = "residue_flags" if source is residue else "anomalies"
        add(history, label, entry.get("count"), f"{source_prefix}.{key}",
            explanation, entry.get("by_system"), affected=entry.get("systems_affected"),
            count_label="Recorded occurrences")

    unmapped = _mapping(headings.get("unmapped_headings"))
    if "unmapped_headings" in headings:
        add(history, "Unmapped section headings", len(unmapped),
            "headings_qc.unmapped_headings",
            "Distinct non-standard headings without a recognised mapping (not a count of affected systems).",
            unmapped, count_label="Distinct headings", machine_examples=False)
    near_miss = _mapping(headings.get("near_miss_banners"))
    add(history, "Systems with near-miss PORTS banners",
        near_miss.get("systems_affected"), "headings_qc.near_miss_banners.systems_affected",
        "Systems with potentially unusual banner spacing.", near_miss.get("by_system"),
        affected=near_miss.get("systems_affected"), count_label="Systems")

    ini = group("Gaming History INI coverage", "summary_ini", "ini", "ini_parsing_summary.json")
    ini_totals = _mapping(data.ini_summary.get("totals"))
    for label, key in (
        ("Missing game-status classification", "missing_in_game_status"),
        ("Missing category classification", "missing_in_category"),
        ("Missing type classification", "missing_in_type"),
    ):
        add(ini, label, ini_totals.get(key), "totals." + key,
            "Coverage relative to the union of machine names in the three INIs, not every MAME machine; not necessarily a parsing error.",
            count_label="Machines")

    transform = group("Transformation", "summary_transform", "transform", "transform_summary.json")
    counts = _mapping(data.transform_summary.get("counts"))
    audio = _mapping(counts.get("audio"))
    add(transform, "Audio channel/speaker mismatches",
        audio.get("channel_speaker_mismatches"), "counts.audio.channel_speaker_mismatches",
        "Records flagged by the transform's audio comparison.", audio.get("mismatch_examples"),
        count_label="Records")
    errors = data.transform_summary.get("errors")
    if isinstance(errors, list):
        add(transform, "Recorded transformation errors", len(errors), "errors",
            "Entries explicitly recorded as errors by the transformer.", errors,
            count_label="Errors")
    title_counts = _mapping(data.transform_summary.get("title_anomaly_counts"))
    if "title_anomaly_counts" in data.transform_summary:
        add(transform, "Title anomalies (reported instances)",
            sum(v for v in title_counts.values() if type(v) is int and v > 0),
            "title_anomaly_counts",
            "Sum of title-anomaly category counts; categories may overlap.", title_counts,
            count_label="Category instances", machine_examples=False)

    publication = _mapping(data.transform_summary.get("publication"))
    add(transform, "Parents deferred from publication", publication.get("deferred_parents"),
        "publication.deferred_parents",
        "Raw PORTS-bearing parents retained but not published; deferral does not imply a parser error.",
        publication.get("deferred_machine_reasons"), count_label="Parents")
    navigation = _mapping(data.transform_summary.get("wiki_navigation"))
    add(transform, "Wiki navigation conflicts", navigation.get("conflicts_total"),
        "wiki_navigation.conflicts_total",
        "Recorded page or redirect conflicts requiring interpretation; not necessarily a defect.",
        count_label="Conflicts")
    snaps = _mapping(data.transform_summary.get("snaps_coverage"))
    add(transform, "PORTS-bearing parents without SNAPS classification",
        snaps.get("ports_parents_missing"), "snaps_coverage.ports_parents_missing",
        "Recorded SNAPS classification coverage gap; does not independently determine publication eligibility.",
        count_label="Parents")

    return groups
