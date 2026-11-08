"""Read-only, bounded presentation of the Transform stage summary.

This module never re-evaluates publication eligibility. It reports figures
already recorded by the transformer, distinguishing raw inclusion from release
publication and keeping missing values distinct from recorded zeroes.
"""
from __future__ import annotations

from typing import Any

SAMPLE_LIMIT = 5
GROUP_LIMIT = 12


def _map(obj: Any) -> dict:
    return obj if isinstance(obj, dict) else {}


def _count(obj: Any) -> int | None:
    return obj if type(obj) is int and obj >= 0 else None


def _samples(obj: Any) -> list[str]:
    """Get up to five machine names, without rendering Python structures."""
    if isinstance(obj, dict):
        values = obj.keys()
    elif isinstance(obj, (list, tuple)):
        values = obj
    else:
        return []
    result: list[str] = []
    for item in values:
        value = item.get("machine") if isinstance(item, dict) else item
        if isinstance(value, str) and value.strip():
            result.append(value.strip())
        if len(result) == SAMPLE_LIMIT:
            break
    return result


def _metric(items: list[dict], label: str, node: dict, key: str, path: str) -> None:
    val = _count(node.get(key))
    if val is not None:
        items.append({"label": label, "value": val, "path": f"{path}.{key}"})


def _groups(source: Any, path: str) -> dict:
    rows = [{"name": str(k), "count": v} for k, v in _map(source).items()
            if _count(v) is not None]
    rows.sort(key=lambda r: (-r["count"], r["name"].casefold()))
    return {"rows": rows[:GROUP_LIMIT], "total": len(rows), "path": path}


def _artefacts(source: Any, *, kind: str) -> list[dict]:
    records = source if isinstance(source, list) else []
    result = []
    for record in records:
        if not isinstance(record, dict):
            continue
        path = record.get("path") or record.get("name")
        if not isinstance(path, str) or not path.strip():
            continue
        result.append({
            "path": path,
            "kind": record.get("kind") if isinstance(record.get("kind"), str) else None,
            "missing": record.get("missing") is True,
            "records": _count(record.get("records")),
            "pages": _count(record.get("pages_count")),
            "redirects": _count(record.get("redirects_count")),
            "conflicts": _count(record.get("conflicts_count")),
            "classifications": _count(record.get("classifications")),
        })
    return result


def build_transform_report(summary: dict) -> dict:
    """Project recorded Transform telemetry into a readable, bounded report."""
    counts = _map(summary.get("counts"))
    publication = _map(summary.get("publication"))
    selection = _map(summary.get("selection"))
    ports = _map(summary.get("ports"))
    snaps = _map(summary.get("snaps_coverage"))
    nav = _map(summary.get("wiki_navigation"))
    provenance = _map(summary.get("provenance"))
    audio = _map(counts.get("audio"))

    stages = []
    for label, node, key, path in (
        ("MAME machines considered", counts, "mame_total", "counts"),
        ("MAME parents", counts, "parents_total", "counts"),
        ("Eligible parents", counts, "eligible_parents", "counts"),
        ("PORTS-bearing parents retained in raw data", publication, "raw_parents", "publication"),
        ("Parents published to ExoticA", publication, "published_parents", "publication"),
        ("Parents deferred from publication", publication, "deferred_parents", "publication"),
    ):
        _metric(stages, label, node, key, path)
    if not any(row["path"] == "publication.raw_parents" for row in stages):
        _metric(stages, "PORTS-bearing parents retained in raw data (legacy)",
                counts, "final_included", "counts")

    ports_metrics = []
    for label, node, key, prefix in (
        ("Gaming History arcade entries", ports, "gh_arcade_entries_total", "ports"),
        ("GH arcade entries with valid PORTS", ports, "gh_arcade_entries_with_ports_total", "ports"),
        ("Included parents with own PORTS", _map(ports.get("included_parents_with_own_ports")), "count", "ports.included_parents_with_own_ports"),
        ("Included clones with PORTS", _map(ports.get("included_clones_with_ports")), "count", "ports.included_clones_with_ports"),
        ("Parents included through clone PORTS only", _map(ports.get("derived")), "parents_included_due_to_clones_only", "ports.derived"),
        ("Parent/clone duplicate PORTS systems", _map(ports.get("parent_clone_duplicate_ports")), "systems_count", "ports.parent_clone_duplicate_ports"),
    ):
        _metric(ports_metrics, label, node, key, prefix)

    snaps_metrics = []
    for label, key in (
        ("SNAPS classifications available", "classifications_total"),
        ("PORTS-bearing parents classified", "ports_parents_classified"),
        ("PORTS-bearing parents without SNAPS classification", "ports_parents_missing"),
        ("PORTS-bearing parents in Arcade group", "ports_parents_in_arcade_group"),
        ("PORTS-bearing parents in non-Arcade groups", "ports_parents_in_non_arcade_group"),
    ):
        _metric(snaps_metrics, label, snaps, key, "snaps_coverage")

    navigation = []
    for label, key in (
        ("Canonical wiki pages", "canonical_pages"),
        ("Redirects", "redirects"),
        ("Recorded navigation conflicts", "conflicts_total"),
    ):
        _metric(navigation, label, nav, key, "wiki_navigation")

    findings = []
    for label, node, key, path, example_list in (
        ("Audio channel/speaker mismatches", audio, "channel_speaker_mismatches", "counts.audio.channel_speaker_mismatches", audio.get("mismatch_examples")),
        ("Parent/clone duplicate PORTS systems", _map(ports.get("parent_clone_duplicate_ports")), "systems_count", "ports.parent_clone_duplicate_ports.systems_count", _map(ports.get("parent_clone_duplicate_ports")).get("systems_list")),
        ("Navigation conflicts", nav, "conflicts_total", "wiki_navigation.conflicts_total", None),
    ):
        number = _count(node.get(key))
        if number is not None and number > 0:
            findings.append({"label": label, "count": number, "path": path,
                             "examples": _samples(example_list)})
    errors = summary.get("errors")
    if isinstance(errors, list) and errors:
        findings.append({"label": "Recorded transformation errors", "count": len(errors),
                         "path": "errors", "examples": _samples(errors)})

    publication_groups = _groups(publication.get("deferred_by_reason"), "publication.deferred_by_reason")
    excluded_groups = _groups(summary.get("excluded_parents_by_reason"), "excluded_parents_by_reason")
    media_groups = _groups(counts.get("media_label_counts"), "counts.media_label_counts")
    title_groups = _groups(summary.get("title_anomaly_counts"), "title_anomaly_counts")
    return {
        "stages": stages,
        "ports": ports_metrics,
        "snaps": snaps_metrics,
        "navigation": navigation,
        "findings": findings,
        "publication_reasons": publication_groups,
        "excluded_reasons": excluded_groups,
        "media": media_groups,
        "title_anomalies": title_groups,
        "inputs": _artefacts(provenance.get("inputs"), kind="input"),
        "outputs": _artefacts(provenance.get("outputs"), kind="output"),
        "sample_limit": SAMPLE_LIMIT,
        "versions": _map(_map(summary.get("header")).get("versions")),
    }
