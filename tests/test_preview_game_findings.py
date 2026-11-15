"""Regression coverage for individual GH findings shown on game pages."""
from __future__ import annotations

from mht.preview.app import create_app
from mht.preview.history_audit_review import build_machine_audit_context
from mht.preview.preview_data import PreviewData


def audit():
    return {
        "schema_id": "mht.history.audit_findings", "release": "0289",
        "provenance": {"inputs": [{"zip_archive": "history289a.zip",
                                    "declared_version": "2.89a"}]},
        "findings": [
            {"machine": "sidearmsu", "section": "PORTS",
             "rule_id": "gh.ports.odd_quotes",
             "source_text": '[US] PC [MS-DOS, 3.25"] (1991) "Arcade Hits"'},
            {"machine": "other", "section": "PORTS",
             "rule_id": "gh.ports.odd_brackets", "source_text": "unclosed <category>"},
        ],
    }


def data(history_audit=None):
    return PreviewData(
        wiki_doc={"games": {}}, wiki_games={},
        trivia_by_machine={"sidearmsu": {"sections": {"trivia": {"blocks": [
            {"kind": "paragraph", "text": "North American release."}]}}},
                           "other": {"sections": {}}},
        mame_machines={"sidearmsu": {"description": "Side Arms"}},
        mame_summary={}, history_summary={}, ini_summary={}, transform_summary={},
        machine_order=["sidearmsu", "other"],
        history_audit=audit() if history_audit is None else history_audit,
    )


def test_unpublished_game_shows_source_audit_without_ports_display():
    app = create_app(data(), version="0289")
    app.config.update(TESTING=True)
    page = app.test_client().get("/game/sidearmsu")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "GH Trivia preview only" in html
    assert "Parsing findings" in html
    assert "gh.ports.odd_quotes" in html
    assert '3.25&#34;' in html or '3.25"' in html
    assert "history289a.zip" in html
    assert "gh.ports.odd_brackets" not in html
    assert 'id="parsing-findings"' in html
    assert "North American release." in html


def test_game_without_findings_has_no_findings_section():
    app = create_app(data({"schema_id": "mht.history.audit_findings", "release": "0289",
                          "findings": []}), version="0289")
    app.config.update(TESTING=True)
    assert b"Parsing findings" not in app.test_client().get("/game/sidearmsu").data


def test_mismatched_release_is_not_shown_as_source_evidence():
    wrong = audit()
    wrong["release"] = "0288"
    assert build_machine_audit_context(wrong, version="0289", machine="sidearmsu")["findings"] == []


def test_malformed_audit_is_not_partially_displayed():
    bad = audit()
    bad["findings"].append({"machine": "sidearmsu"})
    assert build_machine_audit_context(bad, version="0289", machine="sidearmsu")["findings"] == []


def test_exact_machine_matching_and_html_escaping():
    d = audit()
    d["findings"].append({"machine": "sidearms", "section": "PORTS",
                          "rule_id": "gh.ports.odd_quotes", "source_text": "<unsafe>"})
    res = build_machine_audit_context(d, version="0289", machine="sidearmsu")
    assert len(res["findings"]) == 1
    assert res["provenance"]["zip_archive"] == "history289a.zip"
    d["findings"][0]["source_text"] = "<unsafe>"
    app = create_app(data(d), version="0289")
    app.config.update(TESTING=True)
    html = app.test_client().get("/game/sidearmsu").get_data(as_text=True)
    assert "&lt;unsafe&gt;" in html
    assert "<unsafe>" not in html


def test_review_listing_links_to_finding_anchor():
    app = create_app(data(), version="0289")
    app.config.update(TESTING=True)
    html = app.test_client().get("/audit/history").get_data(as_text=True)
    assert '/game/sidearmsu#parsing-findings' in html
