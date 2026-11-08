"""Phase 11: source-backed diagnostics and safe preview links."""
from __future__ import annotations

from mht.preview.app import create_app
from mht.preview.diagnostics import build_diagnostic_groups
from mht.preview.preview_data import PreviewData


def make_data(**overrides):
    values = dict(wiki_doc={}, wiki_games={}, trivia_by_machine={}, mame_machines={},
                  mame_summary={}, history_summary={}, ini_summary={},
                  transform_summary={}, machine_order=[])
    values.update(overrides)
    return PreviewData(**values)


def _find(data, label):
    return next(f for group in build_diagnostic_groups(data)
                for f in group["findings"] if f["label"] == label)


def test_known_machine_link_and_unavailable_machine_plain_text():
    data = make_data(machine_order=["pacman"], history_summary={"anomalies": {
        "odd_number_of_quotes": {"count": 2, "by_system": {"pacman": [1], "other": [2]}}}})
    examples = _find(data, "Odd numbers of quotation marks")["example_items"]
    assert examples == [{"name": "pacman", "machine": "pacman"},
                        {"name": "other", "machine": None}]


def test_machine_links_do_not_require_publication():
    data = make_data(machine_order=["trivia_only"], trivia_by_machine={"trivia_only": {}},
                     history_summary={"anomalies": {"ports_missing_subheadings": {
                         "count": 1, "by_system": {"trivia_only": "excerpt"}}}})
    assert _find(data, "PORTS sections missing subheadings")["example_items"][0]["machine"] == "trivia_only"


def test_heading_and_category_labels_are_never_machine_links():
    data = make_data(machine_order=["ODD HEADING", "ambiguous_title"], history_summary={
        "headings_qc": {"unmapped_headings": {"ODD HEADING": {"count": 4}}}},
        transform_summary={"title_anomaly_counts": {"ambiguous_title": 5}})
    assert _find(data, "Unmapped section headings")["example_items"][0]["machine"] is None
    assert _find(data, "Title anomalies (reported instances)")["example_items"][0]["machine"] is None


def test_occurrences_are_separate_from_explicit_affected_systems():
    data = make_data(history_summary={"anomalies": {"odd_number_of_quotes": {
        "count": 12, "systems_affected": 3, "by_system": {"a": [], "b": [], "c": []}}}})
    f = _find(data, "Odd numbers of quotation marks")
    assert f["count"] == 12 and f["systems_affected"] == 3
    assert f["count_label"] == "Recorded occurrences"


def test_missing_affected_count_not_inferred_from_examples():
    data = make_data(history_summary={"anomalies": {"ports_missing_subheadings": {
        "count": 5, "by_system": {"a": 1, "b": 2}}}})
    assert _find(data, "PORTS sections missing subheadings")["systems_affected"] is None


def test_examples_capped_at_five():
    data = make_data(mame_summary={"totals": {"invalid_displays_dropped": {
        "count": 10, "examples": [{"machine": f"m{i}"} for i in range(9)]}}})
    f = _find(data, "Invalid display records dropped")
    assert len(f["examples"]) == 5
    assert f["examples"][-1] == "m4"


def test_invalid_example_objects_do_not_render_python_dicts():
    data = make_data(transform_summary={"errors": [{"message": "bad"}]})
    assert _find(data, "Recorded transformation errors")["examples"] == []


def test_mame_legacy_mirror_used_only_when_canonical_absent():
    data = make_data(mame_summary={"anomalies": {"dropped_displays": {
        "count": 2, "examples": [{"machine": "a"}]}}})
    f = _find(data, "Invalid display records dropped")
    assert f["count"] == 2 and f["path"] == "anomalies.dropped_displays"


def test_publication_deferrals_are_observations_with_bounded_examples():
    data = make_data(transform_summary={"publication": {
        "deferred_parents": 64,
        "deferred_machine_reasons": {f"m{i}": "reason" for i in range(10)}}})
    f = _find(data, "Parents deferred from publication")
    assert f["count"] == 64 and len(f["examples"]) == 5
    assert "not imply a parser error" in f["explanation"]


def test_navigation_conflicts_and_snaps_coverage_not_inferred():
    data = make_data(transform_summary={"wiki_navigation": {"conflicts_total": 34},
                                            "snaps_coverage": {"ports_parents_missing": 0}})
    assert _find(data, "Wiki navigation conflicts")["count"] == 34
    assert _find(data, "PORTS-bearing parents without SNAPS classification")["count"] == 0
    assert all(f["count"] is not None for g in build_diagnostic_groups(data) for f in g["findings"])


def test_rendered_links_are_valid_and_heading_labels_are_not_links():
    data = make_data(machine_order=["pacman"], mame_machines={"pacman": {"description": "Pac-Man"}},
        history_summary={"anomalies": {"odd_number_of_quotes": {
            "count": 1, "by_system": {"pacman": [1], "missing": [2]}}},
            "headings_qc": {"unmapped_headings": {"pacman": {"count": 2}}}})
    app = create_app(data, version="0289")
    app.config.update(TESTING=True)
    html = app.test_client().get("/diagnostics").get_data(as_text=True)
    assert 'href="/game/pacman"' in html
    assert html.count('href="/game/pacman"') == 1
    assert "missing" in html and 'href="/game/missing"' not in html
    assert "data/releases/0289/summaries/history_parsing_summary.json" in html
    assert "anomalies.odd_number_of_quotes" in html


def test_malformed_or_missing_counts_do_not_become_findings():
    data = make_data(ini_summary={"totals": {"missing_in_type": True,
                                              "missing_in_category": "123"}})
    assert build_diagnostic_groups(data)[2]["findings"] == []
