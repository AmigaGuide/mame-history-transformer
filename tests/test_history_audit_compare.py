import json

import pytest

from mht.audit.history_compare import (
    compare_history_audits,
    write_history_comparison,
)
from mht.utils.io import sha256_file


def make_audit(releases_dir, version, findings):
    """Create a minimal historical audit fixture."""
    folder = releases_dir / version / "summaries"
    folder.mkdir(parents=True, exist_ok=True)

    report = {
        "schema_id": "mht.history.audit_findings",
        "schema_version": "1.0.0",
        "release": version,
        "source": "gaming_history",
        "detectors": {
            "gh.ports.odd_quotes": "1",
        },
        "findings": findings,
    }

    path = folder / "history_audit_findings.json"
    path.write_text(json.dumps(report), encoding="utf-8")


def make_finding(machine="sidearmsu"):
    return {
        "rule_id": "gh.ports.odd_quotes",
        "machine": machine,
        "section": "PORTS",
        "source_text": '[US] PC [MS-DOS, 3.25"] (1991) "Arcade Hits"',
    }


def test_persistent_finding(tmp_path):
    """An observation present throughout remains active."""

    for version in ("0280", "0281", "0282"):
        make_audit(tmp_path, version, [make_finding()])

    result = compare_history_audits(
        tmp_path, ["0280", "0281", "0282"]
    )

    finding = result["findings"][0]

    assert finding["first_observed"] == "0280"
    assert finding["last_observed"] == "0282"
    assert finding["first_absent"] is None
    assert finding["reappeared"] == []
    assert finding["present_in_latest"] is True


def test_disappeared_finding(tmp_path):
    """A finding absent from later releases is recorded historically."""

    make_audit(tmp_path, "0280", [make_finding("stocker")])
    make_audit(tmp_path, "0281", [])
    make_audit(tmp_path, "0282", [])

    result = compare_history_audits(
        tmp_path, ["0280", "0281", "0282"]
    )

    finding = result["findings"][0]

    assert finding["first_observed"] == "0280"
    assert finding["last_observed"] == "0280"
    assert finding["first_absent"] == "0281"
    assert finding["reappeared"] == []
    assert finding["present_in_latest"] is False


def test_reappeared_finding(tmp_path):
    """A finding that returns after an absence is identified."""

    make_audit(tmp_path, "0280", [make_finding()])
    make_audit(tmp_path, "0281", [])
    make_audit(tmp_path, "0282", [make_finding()])

    result = compare_history_audits(
        tmp_path, ["0280", "0281", "0282"]
    )

    finding = result["findings"][0]

    assert finding["first_observed"] == "0280"
    assert finding["last_observed"] == "0282"
    assert finding["first_absent"] == "0281"
    assert finding["reappeared"] == ["0282"]
    assert finding["present_in_latest"] is True


def test_missing_audit_report_is_rejected(tmp_path):
    """A missing release cannot be interpreted as zero findings."""

    make_audit(tmp_path, "0280", [make_finding()])

    with pytest.raises(FileNotFoundError, match="0281"):
        compare_history_audits(
            tmp_path, ["0280", "0281"]
        )


def test_incompatible_detector_versions_are_rejected(tmp_path):
    """Detector changes must not produce misleading historical results."""

    make_audit(tmp_path, "0280", [make_finding()])
    make_audit(tmp_path, "0281", [make_finding()])

    path = (
        tmp_path
        / "0281"
        / "summaries"
        / "history_audit_findings.json"
    )

    report = json.loads(path.read_text(encoding="utf-8"))

    report["detectors"]["gh.ports.odd_quotes"] = "2"

    path.write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Detector definitions differ"):
        compare_history_audits(
            tmp_path, ["0280", "0281"]
        )


def test_repeated_observations_preserve_occurrence_counts(tmp_path):
    """Repeated identical findings must retain their individual counts."""

    make_audit(
        tmp_path,
        "0280",
        [make_finding(), make_finding()],
    )

    make_audit(
        tmp_path,
        "0281",
        [make_finding()],
    )

    result = compare_history_audits(
        tmp_path, ["0280", "0281"]
    )

    assert len(result["findings"]) == 1

    finding = result["findings"][0]

    assert finding["occurrences"] == {
        "0280": 2,
        "0281": 1,
    }

    assert finding["first_observed"] == "0280"
    assert finding["last_observed"] == "0281"
    assert finding["first_absent"] is None
    assert finding["present_in_latest"] is True


def test_out_of_order_releases_are_rejected(tmp_path):
    """Release order must not produce misleading historical dates."""

    with pytest.raises(ValueError, match="chronological order"):
        compare_history_audits(
            tmp_path,
            ["0289", "0280", "0281"],
        )


def test_gh_letter_revisions_are_ordered_correctly(tmp_path):
    """GH letter revisions must follow their corresponding base release."""

    versions = [
        "0287",
        "0287a",
        "0287b",
        "0288",
    ]

    for version in versions:
        make_audit(tmp_path, version, [make_finding()])

    result = compare_history_audits(tmp_path, versions)

    finding = result["findings"][0]

    assert result["releases_compared"] == versions
    assert finding["first_observed"] == "0287"
    assert finding["last_observed"] == "0288"
    assert finding["first_absent"] is None
    assert finding["reappeared"] == []


def test_out_of_order_gh_revisions_are_rejected(tmp_path):
    """A letter revision cannot precede an earlier revision."""

    with pytest.raises(ValueError, match="chronological order"):
        compare_history_audits(
            tmp_path,
            ["0287b", "0287a", "0288"],
        )


def test_multiple_disappearances_and_reappearances(tmp_path):
    """Record every transition without repeating consecutive absences."""

    versions = [
        "0280", "0281", "0282",
        "0283", "0284", "0285",
    ]

    present = {"0280", "0283", "0284"}

    for version in versions:
        findings = [make_finding()] if version in present else []
        make_audit(tmp_path, version, findings)

    result = compare_history_audits(tmp_path, versions)
    finding = result["findings"][0]

    assert finding["first_observed"] == "0280"
    assert finding["last_observed"] == "0284"
    assert finding["first_absent"] == "0281"
    assert finding["reappeared"] == ["0283"]
    assert finding["present_in_latest"] is False

    assert finding["transitions"] == [
        {
            "release": "0281",
            "event": "disappeared",
        },
        {
            "release": "0283",
            "event": "reappeared",
        },
        {
            "release": "0285",
            "event": "disappeared",
        },
    ]


def test_persistent_finding_has_no_transitions(tmp_path):
    """Continuous detection should not generate artificial events."""

    versions = ["0280", "0281", "0282"]

    for version in versions:
        make_audit(tmp_path, version, [make_finding()])

    result = compare_history_audits(tmp_path, versions)
    finding = result["findings"][0]

    assert finding["transitions"] == []
    assert finding["first_absent"] is None
    assert finding["present_in_latest"] is True


def test_comparison_report_is_written_with_provenance(tmp_path):
    """The saved comparison must identify its source audit reports."""

    versions = ["0280", "0281"]

    make_audit(tmp_path, "0280", [make_finding()])
    make_audit(tmp_path, "0281", [])

    output_path = tmp_path / "audits" / "history_comparison_0280_0281.json"

    assert write_history_comparison(
        tmp_path,
        versions,
        output_path,
    )

    assert output_path.is_file()

    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert report["schema_id"] == "mht.history.audit_comparison"
    assert report["schema_version"] == "1.0.0"
    assert report["releases_compared"] == versions

    assert len(report["findings"]) == 1

    finding = report["findings"][0]

    assert finding["first_observed"] == "0280"
    assert finding["last_observed"] == "0280"
    assert finding["first_absent"] == "0281"
    assert finding["transitions"] == [
        {
            "release": "0281",
            "event": "disappeared",
        }
    ]

    sources = report["provenance"]["source_audits"]

    assert len(sources) == 2

    for source, version in zip(sources, versions):
        expected_path = (
            tmp_path
            / version
            / "summaries"
            / "history_audit_findings.json"
        )

        assert source["release"] == version
        assert source["path"] == expected_path.as_posix()
        assert source["sha256"] == sha256_file(expected_path)


def test_comparison_report_is_reproducible(tmp_path):
    """Unchanged audit inputs must produce identical comparison JSON."""

    versions = ["0280", "0281"]

    make_audit(tmp_path, "0280", [make_finding()])
    make_audit(tmp_path, "0281", [make_finding()])

    output_path = tmp_path / "audits" / "comparison.json"

    assert write_history_comparison(
        tmp_path, versions, output_path
    )

    first_content = output_path.read_bytes()

    assert write_history_comparison(
        tmp_path, versions, output_path
    )

    second_content = output_path.read_bytes()

    assert first_content == second_content


def test_missing_source_does_not_write_comparison(tmp_path):
    """An incomplete audit sequence must not produce a report."""

    make_audit(tmp_path, "0280", [make_finding()])

    output_path = tmp_path / "audits" / "comparison.json"

    with pytest.raises(FileNotFoundError, match="0281"):
        write_history_comparison(
            tmp_path,
            ["0280", "0281"],
            output_path,
        )

    assert not output_path.exists()
