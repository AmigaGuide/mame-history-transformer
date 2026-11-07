"""Regression tests for read-only, source-backed preview diagnostics."""
from __future__ import annotations

from mht.preview.app import create_app
from mht.preview.diagnostics import build_diagnostic_groups
from mht.preview.preview_data import PreviewData


def make_data(**overrides):
    fields = dict(
        wiki_doc={"games": {}}, wiki_games={}, trivia_by_machine={}, mame_machines={},
        mame_summary={}, history_summary={}, ini_summary={}, transform_summary={},
        machine_order=[],
    )
    fields.update(overrides)
    return PreviewData(**fields)


def findings(data):
    return [f for group in build_diagnostic_groups(data) for f in group["findings"]]


def test_missing_fields_are_not_reported_as_zero():
    assert findings(make_data()) == []


def test_mame_drops_use_actual_count_and_example():
    data = make_data(mame_summary={"totals": {"invalid_displays_dropped": {
        "count": 3, "examples": [{"machine": "example1"}]
    }}})
    found = findings(data)
    assert found[0]["count"] == 3
    assert found[0]["examples"] == ["example1"]


def test_history_anomaly_categories_use_source_counts():
    data = make_data(history_summary={"anomalies": {
        "odd_number_of_quotes": {"count": 4, "by_system": {"pacman": [1]}},
        "ports_missing_subheadings": {"count": 1, "by_system": {"other": "excerpt"}},
    }})
    found = findings(data)
    assert [f["count"] for f in found] == [4, 1]
    assert found[0]["examples"] == ["pacman"]


def test_unmapped_headings_count_distinct_headings():
    data = make_data(history_summary={"headings_qc": {"unmapped_headings": {
        "UNKNOWN": {"count": 7, "systems": ["a", "b"]}
    }}})
    found = findings(data)
    assert len(found) == 1
    assert found[0]["count"] == 1
    assert "Distinct" in found[0]["explanation"]


def test_ini_coverage_is_not_labelled_error():
    data = make_data(ini_summary={"totals": {"missing_in_type": 9}})
    found = findings(data)
    assert len(found) == 1
    assert found[0]["count"] == 9
    assert "not necessarily a parsing error" in found[0]["explanation"]


def test_transform_errors_and_audio_are_independent():
    data = make_data(transform_summary={
        "counts": {"audio": {"channel_speaker_mismatches": 2}},
        "errors": [{"message": "example"}],
    })
    assert [f["count"] for f in findings(data)] == [2, 1]


def test_zero_count_preserved_when_reported():
    data = make_data(ini_summary={"totals": {"missing_in_category": 0}})
    assert findings(data)[0]["count"] == 0


def test_diagnostics_route_and_home_link():
    app = create_app(make_data(mame_summary={"totals": {
        "invalid_displays_dropped": {"count": 2, "examples": []}
    }}), version="0289")
    app.config.update(TESTING=True)
    client = app.test_client()
    page = client.get("/diagnostics")
    assert page.status_code == 200
    assert b"Invalid display records dropped" in page.data
    assert b"not a quality score" in page.data
    assert b"/diagnostics" in client.get("/").data
