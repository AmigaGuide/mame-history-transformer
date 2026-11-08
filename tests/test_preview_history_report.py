"""Phase 10B tests: meaningful GH summary with bounded examples."""
from __future__ import annotations

from mht.preview.history_report import build_history_report
from mht.preview.app import create_app
from mht.preview.preview_data import PreviewData


def _data(summary):
    return PreviewData(wiki_doc={}, wiki_games={}, trivia_by_machine={}, mame_machines={},
                       mame_summary={}, history_summary=summary, ini_summary={},
                       transform_summary={}, machine_order=[])


def test_platform_counts_and_five_examples():
    summary = {'found': {'platforms_found': {'by_platform': {'Amiga': {
        'systems_count': 9, 'systems': ['a', 'b', 'c', 'd', 'e', 'f']}}}}}
    row = build_history_report(summary)['platforms']['rows'][0]
    assert row['count'] == 9
    assert row['examples'] == ['a', 'b', 'c', 'd', 'e']


def test_platforms_rank_by_count_and_limit_rows():
    rows = {f'platform{i}': {'systems_count': i, 'systems': []} for i in range(20)}
    group = build_history_report({'found': {'platforms_found': {'by_platform': rows}}})['platforms']
    assert group['total_groups'] == 20
    assert len(group['rows']) == 12
    assert group['rows'][0]['count'] == 19


def test_occurrences_not_confused_with_systems():
    summary = {'anomalies': {'odd_number_of_quotes': {
        'count': 10, 'systems_affected': 3, 'by_system': {'a': [1], 'b': [2], 'c': [3]}}}}
    row = build_history_report(summary)['findings'][0]
    assert (row['count'], row['systems_affected']) == (10, 3)


def test_missing_affected_count_is_not_inferred():
    row = build_history_report({'anomalies': {'ports_missing_subheadings': {
        'count': 3, 'by_system': {'a': 'x'}}}})['findings'][0]
    assert row['systems_affected'] is None
    assert row['examples'] == ['a']


def test_unmapped_headings_count_distinct_labels_not_systems():
    report = build_history_report({'headings_qc': {'unmapped_headings': {
        'Odd spelling': {'count': 6, 'systems': ['a']}, 'Unknown': {'count': 2, 'systems': ['b']}}}})
    finding = report['findings'][0]
    assert finding['count'] == 2 and finding['systems_affected'] is None
    assert finding['examples'] == ['Odd spelling', 'Unknown']


def test_no_nested_repr_or_sentinel_in_html():
    summary = {'header': {'versions': {'gh_version': '2.89'}},
               'found': {'platforms_found': {'by_platform': {'Amiga': {
                   'systems_count': 8, 'systems': ['one','two','three','four','five','six'],
                   'hidden': 'DO_NOT_PRINT'}}}}}
    app = create_app(_data(summary), version='0289')
    app.config.update(TESTING=True)
    result = app.test_client().get('/summary/history')
    html = result.get_data(as_text=True)
    assert result.status_code == 200
    assert 'history_parsing_summary.json' in html
    assert 'Amiga' in html and 'one, two, three, four, five' in html
    assert 'six' not in html and 'DO_NOT_PRINT' not in html
    assert "'systems_count':" not in html
    assert '/diagnostics' in html


def test_missing_summary_renders_without_guessing_zero():
    app = create_app(_data({}), version='0289')
    app.config.update(TESTING=True)
    result = app.test_client().get('/summary/history')
    assert result.status_code == 200
    assert b'No recognised totals recorded' in result.data


def test_zero_counts_not_presented_as_findings():
    r = build_history_report({'anomalies': {'odd_number_of_quotes': {'count': 0}}})
    assert r['findings'] == []


def test_zero_affected_systems_without_occurrence_count_is_not_a_finding():
    summary = {
        "anomalies": {
            "unexpected_platform_categories": {
                "unique": 0,
                "systems_affected": 0,
                "by_category": {},
            }
        }
    }

    report = build_history_report(summary)

    assert report["findings"] == []
