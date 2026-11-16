"""Focused tests for read-only Transformation observations."""
from mht.preview.app import create_app
from mht.preview.preview_data import PreviewData
from mht.preview.transform_findings_review import (build_transform_findings_review,
                                                    build_machine_transform_findings)


def summary():
    return {'title_anomaly_counts': {'unbalanced_round_brackets': 1},
            'title_anomalies': {'unbalanced_round_brackets': [
                {'machine': 'pacman', 'example': '<unsafe>', 'pre_override': True}]},
            'ports': {'parent_clone_duplicate_ports': {'systems_count': 2,
                                                        'systems_list': ['pacman', 'absent']}},
            'wiki_navigation': {'conflicts_total': 3, 'page_name_collisions': 1,
                                'redirect_conflicts': 2, 'redirect_page_collisions': 0}}


def data(doc):
    return PreviewData(wiki_doc={}, wiki_games={}, trivia_by_machine={'pacman': {'sections': {}}},
        mame_machines={'pacman': {'description': 'Pac-Man'}}, mame_summary={}, history_summary={},
        ini_summary={}, transform_summary=doc, machine_order=['pacman'])


def test_retains_title_source_and_duplicate_machine_membership():
    r = build_transform_findings_review(summary(), preview_machines=['pacman'])
    assert r['total'] == 3 and r['title_records'] == 1 and r['ports_records'] == 2
    assert r['rows'][0]['evidence'] == '<unsafe>'
    assert {
        row['machine']
        for row in r['rows']
        if row['kind'] == 'ports'
    } == {'pacman', 'absent'}
    assert any(not v['preview'] for v in r['rows'])


def test_navigation_breakdown_does_not_invent_examples():
    r = build_transform_findings_review(summary())
    assert r['navigation_total'] == 3
    assert [x['count'] for x in r['navigation_rows']] == [1, 2, 0]
    assert not any('machine' in x for x in r['navigation_rows'])


def test_filters_search_and_invalid_pagination():
    r = build_transform_findings_review(summary(), query='pac', kind='ports', page='wrong')
    assert r['total'] == 1 and r['page'] == 1
    assert build_transform_findings_review(summary(), kind='bad')['total'] == 3


def test_game_specific_record_not_derived_from_title_counts():
    assert build_machine_transform_findings(summary(), 'pacman')
    assert build_machine_transform_findings(summary(), 'other') == []
    assert build_machine_transform_findings({'title_anomaly_counts': {'bad': 5}}, 'pacman') == []


def test_html_source_escaped_and_unavailable_link_not_created():
    app = create_app(data(summary()), version='0289')
    app.config.update(TESTING=True)
    html = app.test_client().get('/review/transform').get_data(as_text=True)
    assert '&lt;unsafe&gt;' in html and '<unsafe>' not in html
    assert 'Individual' not in html or 'Not available' in html
    assert '/game/pacman#transformation-findings' in html
    assert '/game/absent#transformation-findings' not in html
    assert 'not individual conflicting page names' in html


def test_game_shows_recorded_details_only():
    app = create_app(data(summary()), version='0289')
    app.config.update(TESTING=True)
    html = app.test_client().get('/game/pacman').get_data(as_text=True)
    assert 'id="transformation-findings"' in html
    assert '&lt;unsafe&gt;' in html
    assert 'Parent/clone PORTS duplication' in html


def test_missing_or_malformed_summary_not_interpreted_as_zero():
    r = build_transform_findings_review({'wiki_navigation': {'conflicts_total': '34'}})
    assert r['navigation_total'] is None
    assert r['title_records'] == 0
    assert build_machine_transform_findings({}, 'pacman') == []
