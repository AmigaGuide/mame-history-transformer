"""Real-schema fixtures for chronological GH revision comparisons."""
import hashlib
import json

import pytest

from mht.audit.history_compare import (
    compare_history_audits, compare_history_revision_snapshots,
    write_history_comparison,
)


def _snapshot(root, revision, findings, *, detector="1", corrupt_archive=False):
    base = revision[:4]
    archive = f"history{int(base)}{revision[4:]}.zip"
    audit = {
        "schema_id": "mht.history.audit_findings",
        "release": base,
        "detectors": {"gh.ports.odd_quotes": detector},
        "findings": findings,
        "provenance": {"inputs": [{
            "zip_archive": archive, "zip_member": "history/history.xml"
        }]},
    }
    wrapper = {
        "schema_id": "mht.gh.audit_snapshot", "schema_version": "1.0.0",
        "release": base,
        "revision_archive": "history999.zip" if corrupt_archive else archive,
        "source_member": "history/history.xml",
        "audit": audit,
    }
    p = root / base / "summaries" / "gh_audit_revisions" / f"{archive[:-4]}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(wrapper), encoding="utf-8")
    return p


def _finding(text='[US] PC [MS-DOS, 3.25"]'):
    return {"rule_id": "gh.ports.odd_quotes", "machine": "sidearmsu",
            "section": "PORTS", "source_text": text}


def test_persistent_across_same_base_release(tmp_path):
    _snapshot(tmp_path, "0289", [_finding()])
    _snapshot(tmp_path, "0289a", [_finding()])
    result = compare_history_revision_snapshots(tmp_path, ["0289", "0289a"])
    assert result["releases_compared"] == ["0289", "0289a"]
    assert len(result["findings"]) == 1
    record = result["findings"][0]
    assert record["occurrences"] == {"0289": 1, "0289a": 1}
    assert record["first_absent"] is None and record["present_in_latest"]


def test_disappearance_and_new_finding(tmp_path):
    _snapshot(tmp_path, "0289", [_finding()])
    _snapshot(tmp_path, "0289a", [_finding('new text')])
    result = compare_history_revision_snapshots(tmp_path, ["0289", "0289a"])
    assert len(result["findings"]) == 2
    old = next(r for r in result["findings"] if r["source_text"].startswith('[US]'))
    new = next(r for r in result["findings"] if r["source_text"] == 'new text')
    assert old["first_absent"] == "0289a"
    assert new["first_observed"] == "0289a"


def test_incompatible_detectors_are_rejected(tmp_path):
    _snapshot(tmp_path, "0289", [_finding()])
    _snapshot(tmp_path, "0289a", [_finding()], detector="2")
    with pytest.raises(ValueError, match="Detector definitions differ"):
        compare_history_revision_snapshots(tmp_path, ["0289", "0289a"])


def test_bad_archive_binding_is_rejected(tmp_path):
    _snapshot(tmp_path, "0289", [_finding()])
    _snapshot(tmp_path, "0289a", [], corrupt_archive=True)
    with pytest.raises(ValueError, match="does not match"):
        compare_history_revision_snapshots(tmp_path, ["0289", "0289a"])


def test_missing_revision_snapshot_is_not_zero_findings(tmp_path):
    _snapshot(tmp_path, "0289", [_finding()])
    with pytest.raises(FileNotFoundError, match="history289a.json"):
        compare_history_revision_snapshots(tmp_path, ["0289", "0289a"])


def test_writer_uses_snapshot_paths_for_provenance(tmp_path):
    before = _snapshot(tmp_path, "0289", [_finding()])
    after = _snapshot(tmp_path, "0289a", [_finding()])
    target = tmp_path / "comparison.json"
    assert write_history_comparison(
        tmp_path, ["0289", "0289a"], target, revision_snapshots=True
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert [item["path"] for item in payload["provenance"]["source_audits"]] == [
        before.as_posix(), after.as_posix()
    ]
    assert payload["provenance"]["source_audits"][0]["sha256"] == (
        hashlib.sha256(before.read_bytes()).hexdigest()
    )


def test_legacy_release_mode_is_unchanged(tmp_path):
    for release in ["0288", "0289"]:
        p = tmp_path / release / "summaries" / "history_audit_findings.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "schema_id": "mht.history.audit_findings", "release": release,
            "detectors": {"gh.ports.odd_quotes": "1"}, "findings": [_finding()],
        }), encoding="utf-8")
    result = compare_history_audits(tmp_path, ["0288", "0289"])
    assert result["findings"][0]["present_in_latest"]
