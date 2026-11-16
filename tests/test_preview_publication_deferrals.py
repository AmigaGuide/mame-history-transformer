"""Focused checks of read-only publication-deferral browsing."""
from mht.preview.app import create_app
from mht.preview.preview_data import PreviewData
from mht.preview.publication_deferrals import PAGE_SIZE, build_publication_review, machine_deferred_reason


def _data(summary):
    return PreviewData(wiki_doc={}, wiki_games={},
        trivia_by_machine={"known": {"sections": {}}},
        mame_machines={"known": {"description": "Known"}},
        mame_summary={}, history_summary={}, ini_summary={},
        transform_summary=summary, machine_order=["known"])


def _summary():
    return {"publication": {"deferred_parents": 2,
        "deferred_machine_reasons": {"known": "Not Arcade", "missing": "Unknown <test>"}}}


def test_machine_reason_uses_source_mapping_only():
    assert machine_deferred_reason(_summary(), "known") == "Not Arcade"
    assert machine_deferred_reason(_summary(), "other") is None
    assert machine_deferred_reason({"publication": {"deferred_machine_reasons": {"known": 1}}}, "known") is None


def test_rows_include_machines_without_preview_pages():
    r = build_publication_review(_summary(), preview_machines=["known"])
    assert r["total"] == 2
    assert [(x["machine"], x["preview"]) for x in r["rows"]] == [("known", True), ("missing", False)]


def test_search_reason_and_invalid_page():
    r = build_publication_review(_summary(), preview_machines=[], query="<TEST>", page="bogus")
    assert [x["machine"] for x in r["rows"]] == ["missing"]
    assert r["page"] == 1
    r = build_publication_review(_summary(), preview_machines=[], reason="Not Arcade")
    assert [x["machine"] for x in r["rows"]] == ["known"]


def test_pagination_bounded_and_summary_untouched():
    s = {"publication": {"deferred_machine_reasons": {f"m{i:03}": "r" for i in range(PAGE_SIZE+5)}}}
    r = build_publication_review(s, preview_machines=[], page="2")
    assert len(r["rows"]) == 5 and r["pages"] == 2
    assert len(s["publication"]["deferred_machine_reasons"]) == PAGE_SIZE+5


def test_page_escapes_source_and_never_links_missing_machine():
    app = create_app(_data(_summary()), version="0289")
    app.config.update(TESTING=True)
    text = app.test_client().get("/review/publication").get_data(as_text=True)
    assert "Unknown &lt;test&gt;" in text and "Unknown <test>" not in text
    assert "/game/known#publication-deferral" in text
    assert "/game/missing" not in text
    assert "Recorded deferred-parent total" in text


def test_existing_game_has_its_reason_and_diagnostics_link():
    app = create_app(_data(_summary()), version="0289")
    app.config.update(TESTING=True)
    game = app.test_client().get("/game/known").get_data(as_text=True)
    diag = app.test_client().get("/diagnostics").get_data(as_text=True)
    assert 'id="publication-deferral"' in game
    assert "Not Arcade" in game
    assert "/review/publication" in diag


def test_missing_count_is_not_reported_as_zero():
    r = build_publication_review({"publication": {"deferred_machine_reasons": {"x": "r"}}}, preview_machines=[])
    assert r["recorded_total"] is None
