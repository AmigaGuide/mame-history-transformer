"""Read-only, source-backed listing of individual Gaming History audit findings.

This is presentation only. The parser, audit reports and source ZIPs are not edited.
"""
from __future__ import annotations

from collections import Counter
from math import ceil
from typing import Any, Iterable

PAGE_SIZE = 50


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _page(value: str, page_count: int) -> int:
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = 1
    return min(max(1, requested), page_count)


def build_history_audit_context(
    document: dict,
    *,
    version: str,
    machines: Iterable[str],
    query: str = "",
    rule: str = "",
    page: str = "1",
) -> dict:
    """Build a page of exact audit observations, never inferred errors.

    Missing historic audits are expected. Mismatched or malformed audit
    documents are reported as unavailable, rather than presented as evidence
    belonging to the selected release.
    """
    result = {
        "error": None,
        "query": (query or "").strip(),
        "rule": (rule or "").strip(),
        "rules": [],
        "rows": [],
        "total": 0,
        "selected_total": 0,
        "page": 1,
        "page_count": 1,
        "page_size": PAGE_SIZE,
        "provenance": {},
        "detectors": {},
    }
    if not document:
        result["error"] = "No individual GH History audit is available for this release."
        return result
    if not isinstance(document, dict) or document.get("schema_id") != "mht.history.audit_findings":
        result["error"] = "The GH History audit has an unrecognised schema."
        return result
    if document.get("release") != version:
        result["error"] = "The GH History audit does not identify the selected release."
        return result

    raw_findings = document.get("findings")
    if not isinstance(raw_findings, list) or any(not isinstance(item, dict) for item in raw_findings):
        result["error"] = "The GH History audit contains malformed findings."
        return result
    if any(not all(isinstance(item.get(field), str) for field in
                   ("machine", "section", "rule_id", "source_text")) for item in raw_findings):
        result["error"] = "The GH History audit contains incomplete finding identities."
        return result

    prov_inputs = _mapping(document.get("provenance")).get("inputs")
    if isinstance(prov_inputs, list) and prov_inputs and isinstance(prov_inputs[0], dict):
        result["provenance"] = prov_inputs[0]
    result["detectors"] = _mapping(document.get("detectors"))
    result["total"] = len(raw_findings)
    counts = Counter(item["rule_id"] for item in raw_findings)
    result["rules"] = [{"name": name, "count": counts[name]} for name in sorted(counts)]

    search = result["query"].casefold()
    selected = [item for item in raw_findings if
                (not result["rule"] or item["rule_id"] == result["rule"]) and
                (not search or any(search in item[field].casefold() for field in
                                   ("machine", "section", "rule_id", "source_text")))]
    result["selected_total"] = len(selected)
    result["page_count"] = max(1, ceil(len(selected) / PAGE_SIZE))
    result["page"] = _page(page, result["page_count"])

    available = set(machines)
    start = (result["page"] - 1) * PAGE_SIZE
    result["rows"] = [{
        "machine": item["machine"],
        "machine_link": item["machine"] in available,
        "section": item["section"],
        "rule_id": item["rule_id"],
        "source_text": item["source_text"],
        "value": item.get("value"),
    } for item in selected[start:start + PAGE_SIZE]]
    return result


def build_machine_audit_context(document: dict, *, version: str, machine: str) -> dict:
    """Return exact recorded findings for one game, independent of Wiki eligibility.

    Report integrity is checked before showing evidence: an old or malformed
    audit must not be silently attributed to the selected release.
    """
    result = {"findings": [], "provenance": {}}
    if (not isinstance(document, dict) or
            document.get("schema_id") != "mht.history.audit_findings" or
            document.get("release") != version):
        return result

    findings = document.get("findings")
    if not isinstance(findings, list) or any(
        not isinstance(item, dict) or not all(
            isinstance(item.get(key), str)
            for key in ("machine", "section", "rule_id", "source_text")
        ) for item in findings
    ):
        return result

    provenance_inputs = _mapping(document.get("provenance")).get("inputs")
    if (isinstance(provenance_inputs, list) and provenance_inputs
            and isinstance(provenance_inputs[0], dict)):
        result["provenance"] = provenance_inputs[0]

    result["findings"] = [item for item in findings if item["machine"] == machine]
    return result
