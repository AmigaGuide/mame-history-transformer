"""Read-only review of existing MHT Gaming History diagnostics.

From the repository root:
    python review_history_anomalies.py 0289
    python review_history_anomalies.py 0289 --machine sidearmsu

Uses reports already produced by MHT. Does not change parsing, source data,
outputs, summaries, stage stamps or active release. Findings are observations,
not automatically verified errors in Gaming History.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


EXPLANATIONS = {
    "gh.ports.odd_quotes": (
        "The PORTS parser counted an odd number of quotation marks after "
        "excluding its recognised 3.5-inch and 5.25-inch disk-size marks. "
        "This is a count-based check, not proof of an unmatched title quote."
    ),
    "gh.ports.odd_brackets": (
        "The PORTS parser counted an odd combined total of (), [] and {} "
        "characters. This does not establish which bracket is wrong, and "
        "an even total does not guarantee correct pairing."
    ),
    "gh.ports.unparsable_date": (
        "The PORTS parser extracted a candidate from the first parenthesised "
        "expression remaining after earlier extraction steps, but its date "
        "parser did not accept that candidate. The source may contain a "
        "non-date qualifier in parentheses rather than an invalid date."
    ),
}


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Missing report: {path}")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return result


def number(block: dict, *keys: str) -> int:
    if not isinstance(block, dict):
        return 0
    for key in keys:
        value = block.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return 0


def display(value: object) -> str:
    return str(value) if value is not None and value != "" else "not recorded"


def review(release: str, root: Path, machine_filter: str | None = None) -> None:
    base = root / release / "summaries"
    audit = load_json(base / "history_audit_findings.json")
    summary = load_json(base / "history_parsing_summary.json")
    findings = audit.get("findings") or []
    anomalies = summary.get("anomalies") or {}
    headings = summary.get("headings_qc") or {}
    residue = summary.get("residue_flags") or {}

    if not isinstance(findings, list):
        raise ValueError("Audit report 'findings' must be a list")
    for label, data in (("anomalies", anomalies), ("headings_qc", headings),
                        ("residue_flags", residue)):
        if not isinstance(data, dict):
            raise ValueError(f"Summary '{label}' must be an object")

    provenance_inputs = (audit.get("provenance") or {}).get("inputs") or []
    provenance = provenance_inputs[0] if provenance_inputs else {}

    print(f"GH {release} - anomaly review (existing detectors only)")
    print("=" * 72)
    print("Source archive:", display(provenance.get("zip_archive")))
    print("XML member:    ", display(provenance.get("zip_member")))
    print("Release date:  ", display(provenance.get("declared_date")))
    if machine_filter:
        print("Machine filter: ", machine_filter)

    selected = [f for f in findings
                if machine_filter is None or f.get("machine") == machine_filter]
    print("\nINDIVIDUAL AUDIT FINDINGS - source review candidates")
    print("-" * 72)
    print(f"Findings: {len(selected)}" +
          (f" (of {len(findings)} in release)" if machine_filter else ""))
    for rule, count in sorted(Counter(f.get("rule_id", "unknown") for f in selected).items()):
        print(f"  {rule}: {count}")
    for finding in selected:
        rule = finding.get("rule_id", "unknown")
        print(f"\n  Machine:   {display(finding.get('machine'))}")
        print(f"  Section:   {display(finding.get('section'))}")
        print(f"  Rule:      {rule}")
        print(f"  Why:       {EXPLANATIONS.get(rule, 'No explanation registered for this rule.')}")
        if "value" in finding:
            print(f"  Candidate: {finding['value']!r}")
        print(f"  Source:    {display(finding.get('source_text'))}")

    print("\nSTRUCTURAL OBSERVATIONS - not necessarily source errors")
    print("-" * 72)
    missing = anomalies.get("ports_missing_subheadings") or {}
    excerpts = missing.get("by_system") or {}
    if machine_filter:
        excerpts = {k: v for k, v in excerpts.items() if k == machine_filter}
    print(f"\nPORTS sections without category subheadings: {len(excerpts) if machine_filter else number(missing, 'count')}")
    for machine, excerpt in sorted(excerpts.items()):
        print(f"  {machine}: {excerpt}")
    print("  Note: MHT retains only a 140-character excerpt here. Plain-text PORTS descriptions can be valid.")

    near = headings.get("near_miss_banners") or {}
    near_systems = near.get("by_system") or {}
    if machine_filter:
        near_systems = {k: v for k, v in near_systems.items() if k == machine_filter}
    print(f"\nNear-miss section banners - systems: {len(near_systems)}")
    for machine, lines in sorted(near_systems.items()):
        for line in lines:
            print(f"  {machine}: {line}")

    unmapped = headings.get("unmapped_headings") or {}
    print("\nUnmapped section headings:")
    for heading, details in sorted(unmapped.items()):
        systems = details.get("systems") or []
        if machine_filter:
            systems = [s for s in systems if s == machine_filter]
        if systems:
            print(f"  {heading}: systems: {', '.join(systems)}"
                  + ("" if machine_filter else f"; recorded occurrences: {details.get('count', '?')}"))

    unexpected = anomalies.get("unexpected_platform_categories") or {}
    print("\nUnexpected platform categories:")
    for category, details in sorted((unexpected.get("by_category") or {}).items()):
        systems = details.get("systems") or []
        if machine_filter:
            systems = [s for s in systems if s == machine_filter]
        if systems:
            print(f"  {category}: {', '.join(systems)}")

    null_ports = anomalies.get("null_platform_ports") or {}
    examples = null_ports.get("by_system_lines") or {}
    if machine_filter:
        examples = {k: v for k, v in examples.items() if k == machine_filter}
    print(f"\nPORTS entries without identified platforms: "
          f"{sum((null_ports.get('by_system') or {}).get(k, 0) for k in examples) if machine_filter else number(null_ports, 'count')}")
    for machine, lines in sorted(examples.items()):
        print(f"  {machine}: {' | '.join(map(str, lines))}")
    print("  Note: MHT retains up to three shortened examples per affected system.")

    if not machine_filter:
        print("\nINFORMATIONAL COUNTERS - not errors by themselves")
        print("-" * 72)
        banners = anomalies.get("platform_banners") or {}
        print("PORTS platform banner occurrences:", number(banners, "count"))
        print("Systems affected:", number(banners, "systems_affected"))
        print("Non-standard headings successfully mapped:",
              len(headings.get("mapped_headings") or {}))
        print("Systems with unparsed date residue:",
              number(residue.get("systems_with_residue") or {}, "count"))
    print("\nNo classifications above prove a source error without inspection.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", help="Release folder, e.g. 0289")
    parser.add_argument("--machine", help="Show findings for one machine, e.g. sidearmsu")
    parser.add_argument("--releases-dir", type=Path, default=Path("data/releases"),
                        help="Root of the existing MHT release folders")
    args = parser.parse_args()
    try:
        review(args.release, args.releases_dir, args.machine)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
