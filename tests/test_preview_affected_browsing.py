"""Phase 12B: read-only affected-machine selection and Preview rendering."""
from __future__ import annotations

import pytest

from mht.preview.affected_browsing import PAGE_SIZE, select_affected_machines
from mht.preview.app import create_app
from mht.preview.preview_data import PreviewData
from mht.preview import release_comparison as comparison


def records():
    return {
        "added": {"status": "added", "page_after": "New page", "wiki_regions": [], "trivia_sections": []},
        "gone": {"status": "withdrawn", "page_before": "Old page", "wiki_regions": [], "trivia_sections": []},
        "rename": {"status": "modified", "page_before": "Old title", "page_after": "New title", "wiki_regions": ["Page name"], "trivia_sections": []},
        "both": {"status": "modified", "page_before": "Both", "page_after": "Both", "wiki_regions": ["PORTS"], "trivia_sections": ["trivia"]},
        "only_trivia": {"status": "modified", "page_before": "Trivia", "page_after": "Trivia", "wiki_regions": [], "trivia_sections": ["staff"]},
    }


def selection(**kw):
    return select_affected_machines(records(), preview_machines=["only_trivia", "both"], **kw)


def test_all_rows_are_distinct_and_sorted():
    selected = selection()
    assert selected["total"] == 5
    assert [r["machine"] for r in selected["rows"]] == ["added", "both", "gone", "only_trivia", "rename"]


def test_status_filter_and_page_name_change():
    assert [r["machine"] for r in selection(status="added")["rows"]] == ["added"]
    assert [r["machine"] for r in selection(status="withdrawn")["rows"]] == ["gone"]
    assert [r["machine"] for r in selection(status="modified")["rows"]] == ["both", "only_trivia", "rename"]
    assert [r["machine"] for r in selection(status="renamed")["rows"]] == ["rename"]


def test_change_filters_do_not_double_count():
    assert {r["machine"] for r in selection(change="wiki")["rows"]} == {"added", "gone", "both", "rename"}
    assert {r["machine"] for r in selection(change="trivia")["rows"]} == {"both", "only_trivia"}
    assert {r["machine"] for r in selection(change="both")["rows"]} == {"both"}
    assert {r["machine"] for r in selection(change="trivia-only")["rows"]} == {"only_trivia"}


def test_query_matches_machine_or_either_page_name_case_insensitively():
    assert selection(query="  NEW TITLE  ")["rows"][0]["machine"] == "rename"
    assert selection(query="OLD PAGE")["total"] == 1  # 'gone', not 'rename'
    assert selection(query="ONLY_TRIVIA")["total"] == 1


def test_no_broken_game_links_for_absent_active_preview_records():
    rows = {r["machine"]: r for r in selection()["rows"]}
    assert rows["both"]["preview_available"] is True
    assert rows["only_trivia"]["preview_available"] is True
    assert rows["gone"]["preview_available"] is False
    assert rows["gone"]["status"] == "withdrawn"


def test_pagination_and_out_of_range_request():
    many = {f"m{i:03}": {"status": "modified", "wiki_regions": ["MAME titles"]} for i in range(111)}
    second = select_affected_machines(many, page=2)
    assert second["total"] == 111 and second["page_count"] == 3
    assert len(second["rows"]) == PAGE_SIZE and second["rows"][0]["machine"] == "m050"
    assert select_affected_machines(many, page=999)["page"] == 3
    assert select_affected_machines(many, page="not-number")["page"] == 1


def test_invalid_filters_and_empty_records_are_safe():
    selected = select_affected_machines(None, status="nonsense", change="bad")
    assert selected["total"] == 0 and selected["status"] == "all" and selected["change"] == "all"
    assert select_affected_machines({"bad": []})["total"] == 0


def test_rendered_table_filters_and_links(monkeypatch):
    monkeypatch.setattr(comparison, "available_releases", lambda: ["0288", "0289"])
    def fake_compare(before, after):
        assert (before, after) == ("0288", "0289")
        return {"counts": {"affected_machines": 5, "modified": 3, "trivia_changed_machines": 2},
                "renamed": [], "affected_region_counts": {}, "affected": records()}
    monkeypatch.setattr(comparison, "compare_release_content", fake_compare)
    data = PreviewData(wiki_doc={}, wiki_games={}, trivia_by_machine={"only_trivia": {}},
                       mame_machines={}, mame_summary={}, history_summary={}, ini_summary={},
                       transform_summary={}, machine_order=["both", "only_trivia"])
    app = create_app(data, version="0289")
    app.config.update(TESTING=True)
    client = app.test_client()
    html = client.get("/compare?before=0288&after=0289&status=withdrawn").get_data(as_text=True)
    assert "No longer published" in html and "gone" in html
    assert 'href="/game/gone"' not in html
    html = client.get("/compare?before=0288&after=0289&change=trivia-only").get_data(as_text=True)
    assert 'href="/game/only_trivia"' in html
    assert "staff" in html and 'href="/game/both"' not in html
    assert "201" not in html  # stubbed comparator count, not fabricated by browsing


def test_schema_error_does_not_show_browsing(monkeypatch):
    monkeypatch.setattr(comparison, "available_releases", lambda: ["0287", "0288"])
    def bad_schema(*_):
        raise ValueError("Wiki schemas differ ('1.1.0' vs '1.2.0')")
    monkeypatch.setattr(comparison, "compare_release_content", bad_schema)
    data = PreviewData(wiki_doc={}, wiki_games={}, trivia_by_machine={}, mame_machines={},
                       mame_summary={}, history_summary={}, ini_summary={}, transform_summary={}, machine_order=[])
    app = create_app(data, version="0288")
    app.config.update(TESTING=True)
    html = app.test_client().get('/compare').get_data(as_text=True)
    assert "Wiki schemas differ" in html
    assert "Affected machines</h2>" not in html


def test_empty_filter_does_not_change_headline_counts(monkeypatch):
    monkeypatch.setattr(comparison, "available_releases", lambda: ["0288", "0289"])
    monkeypatch.setattr(comparison, "compare_release_content", lambda *_: {
        "counts": {"affected_machines": 201}, "renamed": [], "affected_region_counts": {}, "affected": records()})
    data = PreviewData(wiki_doc={}, wiki_games={}, trivia_by_machine={}, mame_machines={},
                       mame_summary={}, history_summary={}, ini_summary={}, transform_summary={}, machine_order=[])
    app = create_app(data, version="0289")
    app.config.update(TESTING=True)
    html = app.test_client().get('/compare?status=withdrawn&q=NONEXISTENT').get_data(as_text=True)
    assert '201' in html
    assert '0 matching machines' in html
