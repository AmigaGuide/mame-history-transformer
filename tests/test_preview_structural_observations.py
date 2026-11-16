"""Focused regression checks for GH structural evidence in Preview."""
from __future__ import annotations

from mht.preview.app import create_app
from mht.preview.history_structural_observations import (
    MAX_BANNER_LINES, build_machine_structural_observations,
)
from mht.preview.preview_data import PreviewData


def _summary():
    return {
        "anomalies": {"ports_missing_subheadings": {
            "count": 2, "by_system": {
                "pacman": "[US] PC <unusual> entry", "other": "different source"}}},
        "headings_qc": {"near_miss_banners": {
            "systems_affected": 2, "by_system": {
                "pacman": ["-Option Menu-", "-Secret <x>-"],
                "other": ["-Other-"],
            }}},
    }


def _data(summary=None):
    return PreviewData(
        wiki_doc={"games": {}}, wiki_games={},
        trivia_by_machine={"pacman": {"sections": {}}, "other": {"sections": {}}},
        mame_machines={"pacman": {"description": "Pac-Man"}},
        mame_summary={}, history_summary=_summary() if summary is None else summary,
        ini_summary={}, transform_summary={}, machine_order=["pacman", "other"],
        history_audit={},
    )


def test_only_machine_specific_recorded_evidence_is_shown():
    rows = build_machine_structural_observations(_summary(), "pacman")
    assert len(rows) == 2
    assert rows[0]["items"] == ["[US] PC <unusual> entry"]
    assert rows[1]["items"] == ["-Option Menu-", "-Secret <x>-"]
    assert "different source" not in str(rows)
    assert "140" in rows[0]["source_label"]


def test_missing_or_malformed_summary_is_ignored_without_inventing_findings():
    assert build_machine_structural_observations({}, "pacman") == []
    assert build_machine_structural_observations(_summary(), "absent") == []
    assert build_machine_structural_observations({"headings_qc": {
        "near_miss_banners": {"by_system": {"pacman": "bad shape"}}}}, "pacman") == []


def test_banner_display_limit_is_explicit_and_does_not_change_summary():
    summary = {"headings_qc": {"near_miss_banners": {"by_system": {
        "pacman": [f"-Banner {i}-" for i in range(MAX_BANNER_LINES + 3)]}}}}
    rows = build_machine_structural_observations(summary, "pacman")
    assert len(rows[0]["items"]) == MAX_BANNER_LINES
    assert rows[0]["omitted"] == 3
    assert len(summary["headings_qc"]["near_miss_banners"]["by_system"]["pacman"]) == MAX_BANNER_LINES + 3


def test_game_page_displays_structural_observations_and_escapes_source():
    app = create_app(_data(), version="0289")
    app.config.update(TESTING=True)
    html = app.test_client().get("/game/pacman").get_data(as_text=True)
    assert 'id="structural-observations"' in html
    assert 'href="#structural-observations"' in html
    assert "PORTS without category subheadings" in html
    assert "Near-miss section banners" in html
    assert "&lt;unusual&gt;" in html and "<unusual>" not in html
    assert "&lt;x&gt;" in html and "<x>" not in html
    assert "different source" not in html
    assert "not necessarily an error" in html
    assert "GH Trivia preview only" in html


def test_game_without_structural_evidence_has_no_new_section():
    app = create_app(_data({}), version="0289")
    app.config.update(TESTING=True)
    assert b"Structural observations" not in app.test_client().get("/game/pacman").data


def test_diagnostics_examples_jump_to_corresponding_structural_section():
    app = create_app(_data(), version="0289")
    app.config.update(TESTING=True)
    html = app.test_client().get("/diagnostics").get_data(as_text=True)
    assert html.count('/game/pacman#structural-observations') == 2
    assert '/game/other#structural-observations' in html
    assert "Systems with near-miss section banners" in html


def test_unrelated_diagnostics_links_remain_unchanged():
    d = _summary()
    d["anomalies"]["odd_number_of_quotes"] = {
        "count": 1, "by_system": {"pacman": ["odd"]}}
    app = create_app(_data(d), version="0289")
    app.config.update(TESTING=True)
    html = app.test_client().get("/diagnostics").get_data(as_text=True)
    assert 'href="/game/pacman"' in html
