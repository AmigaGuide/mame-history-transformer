from collections import Counter, defaultdict
import json

from mht.inputs.history_ports import parse_port_entry
from mht.inputs.history_xml_parser import write_history_audit_findings


def make_parsing_state():
    """Provide the state required by the existing PORTS parser."""
    return {
        "odd_quotes": defaultdict(list),
        "odd_brackets": defaultdict(list),
        "audit_findings": [],
        "publisher_indicators_found": {
            "released_by": 0,
            "by": 0,
            "other_after_date": 0,
            "none": 0,
        },
        "publishers_found": defaultdict(
            lambda: {"count": 0, "systems": []}
        ),
        "titles_found": set(),
        "region_codes": Counter(),
        "models_found": defaultdict(list),
        "additional_tags_found": defaultdict(list),
        "ports_with_comments": 0,
    }


def test_odd_quotes_create_individual_audit_finding():
    """An existing PORTS anomaly should also produce an audit observation."""

    parsing_state = make_parsing_state()

    original_line = '"Unclosed game title (1985) by Example Publisher'

    parse_port_entry(
        original_line,
        system_name="example",
        parsing_state=parsing_state,
    )

    # Existing anomaly reporting must remain intact.
    assert parsing_state["odd_quotes"]["example"] == [original_line]

    # The new audit collector must preserve the individual observation.
    assert parsing_state["audit_findings"] == [
        {
            "rule_id": "gh.ports.odd_quotes",
            "machine": "example",
            "section": "PORTS",
            "source_text": original_line,
        }
    ]


def test_valid_quotes_do_not_create_audit_finding():
    """Ordinary, balanced quotation marks should not be flagged."""

    parsing_state = make_parsing_state()

    parse_port_entry(
        '"Example Game" (1985) by Example Publisher',
        system_name="example",
        parsing_state=parsing_state,
    )

    assert parsing_state["audit_findings"] == []
    assert not parsing_state["odd_quotes"]


def test_audit_report_is_written_with_provenance(tmp_path):
    """Audit observations and source provenance survive JSON persistence."""

    output_path = tmp_path / "history_audit_findings.json"

    parsing_state = {
        "audit_findings": [
            {
                "rule_id": "gh.ports.odd_quotes",
                "machine": "sidearmsu",
                "section": "PORTS",
                "source_text": '[US] PC [MS-DOS, 3.25"] (1991) "Arcade Hits"',
            }
        ]
    }

    provenance = {
        "inputs": [
            {
                "zip_archive": "history289.zip",
                "zip_member": "history/history.xml",
                "declared_version": "2.89",
                "declared_date": "2026-08-07",
            }
        ]
    }

    summary = {"provenance": provenance}

    assert write_history_audit_findings(
        parsing_state,
        summary,
        "0289",
        output_path,
    )

    assert output_path.is_file()

    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert report["schema_id"] == "mht.history.audit_findings"
    assert report["schema_version"] == "1.0.0"
    assert report["release"] == "0289"
    assert report["source"] == "gaming_history"
    assert report["provenance"] == provenance
    assert report["detectors"]["gh.ports.odd_quotes"] == "1"
    assert report["findings"] == parsing_state["audit_findings"]


def test_empty_audit_report_is_still_written(tmp_path):
    """A successful audit with no observations must create an output file."""

    output_path = tmp_path / "history_audit_findings.json"

    assert write_history_audit_findings(
        {"audit_findings": []},
        {"provenance": {"inputs": []}},
        "0280",
        output_path,
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert report["release"] == "0280"
    assert report["findings"] == []
    assert report["provenance"] == {"inputs": []}
