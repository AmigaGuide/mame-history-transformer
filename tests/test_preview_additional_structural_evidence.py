"""Focused Preview tests for additional source-backed GH structural evidence."""
from __future__ import annotations

from mht.preview.app import create_app
from mht.preview.history_structural_observations import build_machine_structural_observations
from mht.preview.preview_data import PreviewData


def sample_summary():
    return {
        "anomalies": {"null_platform_ports": {
            "count": 7, "systems_affected": 2,
            "by_system": {"pacman": 5, "other": 2},
            "by_system_lines": {"pacman": ["PORTS <unknown>", "An unusual entry"],
                                "other": ["Not Pac-Man"]}}},
        "headings_qc": {"unmapped_headings": {
            "UNUSUAL <HEADING>": {"count": 3, "systems": ["pacman", "other"]},
            "DIFFERENT": {"count": 1, "systems": ["other"]}}},
    }


def data(summary=None):
    return PreviewData(
        wiki_doc={}, wiki_games={},
        trivia_by_machine={"pacman": {"sections": {}}, "other": {"sections": {}}},
        mame_machines={"pacman": {"description": "Pac-Man"}},
        mame_summary={}, history_summary=sample_summary() if summary is None else summary,
        ini_summary={}, transform_summary={}, machine_order=["pacman", "other"],
    )


def test_existing_summary_evidence_is_specific_to_machine():
    findings = build_machine_structural_observations(sample_summary(), "pacman")
    assert [f["label"] for f in findings] == [
        "PORTS entries without an identified platform", "Unmapped section headings"]
    assert findings[0]["items"] == ["PORTS <unknown>", "An unusual entry"]
    assert findings[1]["items"] == ["UNUSUAL <HEADING>"]
    assert "normalised" in findings[1]["source_label"]
    assert "Not Pac-Man" not in str(findings)


def test_missing_examples_do_not_erase_recorded_count():
    summary = {"anomalies": {"null_platform_ports": {"by_system": {"pacman": 3}}}}
    finding = build_machine_structural_observations(summary, "pacman")[0]
    assert finding["items"] == []
    assert "3 occurrence" in finding["source_label"]


def test_invalid_counts_and_heading_memberships_are_ignored():
    summary = {"anomalies": {"null_platform_ports": {
        "by_system": {"pacman": True}, "by_system_lines": {"pacman": ["not valid count"]}}},
        "headings_qc": {"unmapped_headings": {"HEADING": {"systems": "pacman"}}}}
    assert build_machine_structural_observations(summary, "pacman") == []


def test_source_evidence_escapes_html_and_links_to_panel():
    app = create_app(data(), version="0289")
    app.config.update(TESTING=True)
    client = app.test_client()
    game = client.get("/game/pacman").get_data(as_text=True)
    assert "PORTS entries without an identified platform" in game
    assert "UNUSUAL &lt;HEADING&gt;" in game
    assert "PORTS &lt;unknown&gt;" in game
    assert "<unknown>" not in game
    assert "Not Pac-Man" not in game
    assert 'id="structural-observations"' in game
    diagnostics = client.get("/diagnostics").get_data(as_text=True)
    assert "PORTS entries without identified platforms" in diagnostics
    assert "7" in diagnostics
    assert "Systems affected: 2" in diagnostics
    assert '/game/pacman#structural-observations' in diagnostics


def test_no_new_evidence_does_not_add_panel():
    app = create_app(data({}), version="0289")
    app.config.update(TESTING=True)
    assert b"Structural observations" not in app.test_client().get("/game/pacman").data
