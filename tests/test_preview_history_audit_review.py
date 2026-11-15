"""Read-only individual GH audit findings in the existing Preview."""
from __future__ import annotations

from mht.preview.app import create_app
from mht.preview.history_audit_review import build_history_audit_context
from mht.preview.preview_data import PreviewData


def _audit(count=2):
    findings = [
        {"machine": "sidearmsu", "section": "PORTS", "rule_id": "gh.ports.odd_quotes",
         "source_text": '[US] PC [MS-DOS, 3.25"] (1991) "Arcade Hits"'},
        {"machine": "missing", "section": "PORTS", "rule_id": "gh.ports.odd_brackets",
         "source_text": "Problem [<raw>"},
    ]
    return {
        "schema_id": "mht.history.audit_findings", "release": "0289",
        "provenance": {"inputs": [{"zip_archive": "history289a.zip",
                                    "zip_member": "history/history.xml", "declared_version": "2.89a"}]},
        "detectors": {"gh.ports.odd_quotes": "1", "gh.ports.odd_brackets": "1"},
        "findings": (findings * (count // 2)) + findings[:count % 2],
    }


def _data(audit=None):
    return PreviewData(
        wiki_doc={"games": {}}, wiki_games={}, trivia_by_machine={},
        mame_machines={"sidearmsu": {"description": "Side Arms"}},
        mame_summary={}, history_summary={}, ini_summary={}, transform_summary={},
        machine_order=["sidearmsu"], history_audit=_audit() if audit is None else audit,
    )


def test_exact_findings_and_source_provenance():
    report = build_history_audit_context(_audit(), version="0289", machines=["sidearmsu"])
    assert report["total"] == report["selected_total"] == 2
    assert report["provenance"]["zip_archive"] == "history289a.zip"
    assert report["rows"][0]["source_text"].endswith('"Arcade Hits"')
    assert report["rows"][0]["machine_link"] is True
    assert report["rows"][1]["machine_link"] is False


def test_rule_and_text_filters_intersect():
    report = build_history_audit_context(
        _audit(), version="0289", machines=[], query="MS-DOS", rule="gh.ports.odd_quotes"
    )
    assert report["selected_total"] == 1
    assert report["rows"][0]["machine"] == "sidearmsu"
    report = build_history_audit_context(
        _audit(), version="0289", machines=[], query="MS-DOS", rule="gh.ports.odd_brackets"
    )
    assert report["selected_total"] == 0
    assert report["total"] == 2


def test_missing_audit_is_not_misrepresented_as_no_findings():
    report = build_history_audit_context({}, version="0289", machines=[])
    assert report["error"] and "No individual GH History audit" in report["error"]
    assert report["rows"] == []


def test_wrong_release_or_schema_is_not_displayed():
    wrong_release = build_history_audit_context(_audit(), version="0290", machines=[])
    assert wrong_release["error"] and not wrong_release["rows"]
    doc = _audit()
    doc["schema_id"] = "other"
    assert build_history_audit_context(doc, version="0289", machines=[])["error"]


def test_malformed_findings_are_not_silently_ignored():
    doc = _audit()
    doc["findings"].append({"machine": "partial"})
    report = build_history_audit_context(doc, version="0289", machines=[])
    assert report["error"] and not report["rows"]


def test_pagination_and_out_of_bounds_page():
    doc = _audit(55)
    first = build_history_audit_context(doc, version="0289", machines=[], page="1")
    last = build_history_audit_context(doc, version="0289", machines=[], page="999")
    assert len(first["rows"]) == 50 and first["page_count"] == 2
    assert len(last["rows"]) == 5 and last["page"] == 2
    assert build_history_audit_context(doc, version="0289", machines=[], page="nope")["page"] == 1


def test_html_is_escaped_and_missing_machine_is_not_linked():
    app = create_app(_data(), version="0289")
    app.config.update(TESTING=True)
    page = app.test_client().get("/audit/history")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "history289a.zip" in html
    assert 'href="/game/sidearmsu#parsing-findings"' in html
    assert 'href="/game/missing"' not in html
    assert "&lt;raw&gt;" in html
    assert "<raw>" not in html


def test_diagnostics_links_to_individual_findings_page():
    app = create_app(_data(), version="0289")
    app.config.update(TESTING=True)
    page = app.test_client().get("/diagnostics")
    assert page.status_code == 200
    assert b'/audit/history' in page.data


def test_route_filter_and_empty_state():
    app = create_app(_data(), version="0289")
    app.config.update(TESTING=True)
    page = app.test_client().get('/audit/history?q=nonexistent&rule=gh.ports.odd_quotes')
    assert page.status_code == 200
    assert b'0 matching findings' in page.data
    assert b'No individual audit findings match the current filters.' in page.data
