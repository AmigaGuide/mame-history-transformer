"""Phase 12A: read-only release comparison adapter and Flask presentation."""
from __future__ import annotations

from pathlib import Path

import pytest

from mht.preview import release_comparison as comparison
from mht.preview.app import create_app
from mht.preview.preview_data import PreviewData


def make_data():
    return PreviewData(wiki_doc={}, wiki_games={}, trivia_by_machine={}, mame_machines={},
                       mame_summary={}, history_summary={}, ini_summary={},
                       transform_summary={}, machine_order=[])


def sample_report():
    return {
        'counts': {'affected_machines': 201, 'modified': 181,
                   'trivia_changed_machines': 22, 'added': 1,
                   'withdrawn': 2, 'page_name_changes': 3,
                   'changed_trivia_sections': 35, 'wiki_affected_machines': 184,
                   'trivia_only_machines': 17, 'changed_in_both': 5},
        'scope': 'Generated datasets',
        'renamed': [{'machine': 'raycris', 'before': 'Ray Crisis', 'after': 'RayCrisis'}],
        'affected_region_counts': {'PORTS': 42, 'GH Trivia: Technical': 7},
    }


@pytest.fixture
def prepared(monkeypatch):
    monkeypatch.setattr(comparison, 'available_releases', lambda: ['0287', '0288', '0289'])
    calls = []
    def fake_compare(before, after):
        calls.append((before, after))
        return sample_report()
    monkeypatch.setattr(comparison, 'compare_release_content', fake_compare)
    return calls


def test_default_uses_active_and_numerically_preceding(prepared):
    ctx = comparison.overview_context(active_release='0289', before=None, after=None)
    assert (ctx['before'], ctx['after']) == ('0288', '0289')
    assert prepared == [('0288', '0289')]
    assert ctx['report']['counts']['affected_machines'] == 201


def test_nonconsecutive_previous_release(prepared):
    ctx = comparison.overview_context(active_release='0288', before=None, after=None)
    assert (ctx['before'], ctx['after']) == ('0287', '0288')


def test_unavailable_version_is_rejected_without_comparison(prepared):
    ctx = comparison.overview_context(active_release='0289', before='9999',
                                      after='0289', selected=True)
    assert ctx['report'] is None and ctx['error']
    assert prepared == []


def test_reversed_or_equal_versions_are_rejected(prepared):
    for before, after in [('0289', '0288'), ('0289', '0289')]:
        ctx = comparison.overview_context(active_release='0289', before=before,
                                          after=after, selected=True)
        assert ctx['report'] is None and ctx['error']
    assert prepared == []


def test_only_one_complete_release_is_not_comparable(monkeypatch):
    monkeypatch.setattr(comparison, 'available_releases', lambda: ['0289'])
    ctx = comparison.overview_context(active_release='0289', before=None, after=None)
    assert ctx['report'] is None and 'two complete' in ctx['error']


def test_incomplete_release_directories_are_not_listed(monkeypatch, tmp_path):
    from mht.preview import release_comparison as c
    monkeypatch.setattr(c, 'list_release_versions', lambda: ['0288', '0289', 'oops'])
    monkeypatch.setattr(c, 'exotica_wiki_path', lambda v: tmp_path / v / 'wiki.json')
    monkeypatch.setattr(c, 'exotica_pages_path', lambda v: tmp_path / v / 'pages.json')
    monkeypatch.setattr(c, 'gh_system_trivia_path', lambda v: tmp_path / v / 'trivia.json')
    for name in ('wiki.json', 'pages.json', 'trivia.json'):
        dest = tmp_path / '0289' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text('{}', encoding='utf-8')
    dest = tmp_path / '0288' / 'wiki.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text('{}', encoding='utf-8')
    assert c.available_releases() == ['0289']


def test_invalid_comparator_data_is_reported(monkeypatch, prepared):
    monkeypatch.setattr(comparison, 'compare_release_content', lambda b, a: {'counts': []})
    ctx = comparison.overview_context(active_release='0289', before='0288', after='0289', selected=True)
    assert ctx['report'] is None and 'valid summary counts' in ctx['error']


def test_comparator_value_error_is_displayed(monkeypatch, prepared):
    def fail(b, a):
        raise ValueError('Incompatible Wiki schema versions')
    monkeypatch.setattr(comparison, 'compare_release_content', fail)
    ctx = comparison.overview_context(active_release='0289', before='0288', after='0289', selected=True)
    assert 'Incompatible Wiki schema versions' in ctx['error']


def test_rendered_overview_and_navigation(prepared):
    app = create_app(make_data(), version='0289')
    app.config.update(TESTING=True)
    client = app.test_client()
    response = client.get('/compare')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '201' in html and '181' in html and '22' in html
    assert 'Ray Crisis' in html and 'RayCrisis' in html
    assert 'Compare releases' in client.get('/').get_data(as_text=True)
    assert prepared == [('0288', '0289')]


def test_explicit_selection_is_passed_through(prepared):
    app = create_app(make_data(), version='0289')
    app.config.update(TESTING=True)
    response = app.test_client().get('/compare?before=0287&after=0288')
    assert response.status_code == 200
    assert prepared == [('0287', '0288')]


def test_invalid_selection_renders_error_without_comparator(prepared):
    app = create_app(make_data(), version='0289')
    app.config.update(TESTING=True)
    html = app.test_client().get('/compare?before=../../etc&after=0289').get_data(as_text=True)
    assert 'lack complete comparison datasets' in html
    assert prepared == []


def test_summary_does_not_expand_affected_machine_list(prepared):
    app = create_app(make_data(), version='0289')
    app.config.update(TESTING=True)
    html = app.test_client().get('/compare').get_data(as_text=True)
    assert 'Affected Wiki regions' in html
    assert '201' in html and '<pre>' not in html
