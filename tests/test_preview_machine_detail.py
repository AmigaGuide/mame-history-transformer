"""Phase 12C: single-machine read-only comparison details."""
from __future__ import annotations

import pytest

from mht.preview import machine_detail as detail
from mht.preview import release_comparison as comparison
from mht.preview.app import create_app
from mht.preview.preview_data import PreviewData


def make_data(machines=()):
    return PreviewData(wiki_doc={}, wiki_games={}, trivia_by_machine={}, mame_machines={},
                       mame_summary={}, history_summary={}, ini_summary={},
                       transform_summary={}, machine_order=list(machines))


def affected(status='modified', trivia=('trivia',)):
    return {'xevious': {'status': status, 'page_before': 'Old', 'page_after': 'New' if status == 'modified' else None,
                        'wiki_regions': ['Opening sentence'] if status == 'modified' else [],
                        'trivia_sections': list(trivia)}}


def fake_load(version):
    v = 'previous' if version == '0288' else 'updated'
    return {'games': {'xevious': {'opening_sentence': v, 'unchanged': 'same'}}}, {'xevious': 'Page'}


def test_only_recorded_fields_are_read(monkeypatch):
    monkeypatch.setattr(detail, '_load_release', fake_load)
    monkeypatch.setattr(detail, 'detail_for_machine', lambda *a: '')
    result = detail.build_machine_detail(before='0288', after='0289', machine='xevious',
        affected=affected(trivia=()), modified={'xevious': {'changed_fields': ['opening_sentence']}})
    assert len(result['fields']) == 1
    assert result['fields'][0] == {'name': 'opening_sentence', 'before': 'previous', 'after': 'updated'}
    assert result['renamed'] is True


def test_trivia_uses_existing_diagnostic_formatter(monkeypatch):
    calls = []
    monkeypatch.setattr(detail, '_load_release', lambda *a: pytest.fail('Wiki records should not be loaded'))
    monkeypatch.setattr(detail, 'detail_for_machine', lambda *a: calls.append(a) or '  - [paragraph] old\n  + [paragraph] new')
    result = detail.build_machine_detail(before='0288', after='0289', machine='xevious',
        affected=affected(), modified={})
    assert calls == [('0288', '0289', 'xevious')]
    assert 'old' in result['trivia_text']


def test_added_or_withdrawn_are_not_field_diffs(monkeypatch):
    monkeypatch.setattr(detail, '_load_release', lambda *a: pytest.fail('Do not inspect absent publication'))
    for state in ('added', 'withdrawn'):
        result = detail.build_machine_detail(before='0288', after='0289', machine='xevious',
            affected=affected(status=state, trivia=()), modified={})
        assert result['fields'] == [] and result['status'] == state


def test_unknown_machine_rejected():
    with pytest.raises(LookupError):
        detail.build_machine_detail(before='0288', after='0289', machine='notthere', affected=affected(), modified={})


def test_long_values_are_bounded():
    assert '[display shortened' in detail._display('X' * 6000)
    assert len(detail._display('X' * 6000)) < 2000


def test_missing_field_is_distinct_from_none(monkeypatch):
    monkeypatch.setattr(detail, '_load_release', lambda v: (
        {'games': {'xevious': {} if v == '0288' else {'field': None}}}, {}))
    result = detail.build_machine_detail(before='0288', after='0289', machine='xevious',
        affected=affected(trivia=()), modified={'xevious': {'changed_fields': ['field']}})
    assert result['fields'][0]['before'] == 'Field not present'
    assert result['fields'][0]['after'] == 'null'


@pytest.fixture
def app_client(monkeypatch):
    report = {
        'counts': {'affected_machines': 1}, 'renamed': [], 'affected_region_counts': {},
        'affected': affected(), 'modified': {'xevious': {'changed_fields': ['opening_sentence']}},
    }
    monkeypatch.setattr(comparison, 'available_releases', lambda: ['0288', '0289'])
    monkeypatch.setattr(comparison, 'compare_release_content', lambda a, b: report)
    monkeypatch.setattr(detail, '_load_release', fake_load)
    monkeypatch.setattr(detail, 'detail_for_machine', lambda *a: 'TRIVIA - SECTION MODIFIED\n  - old\n  + new')
    app = create_app(make_data(['xevious']), version='0289')
    app.config.update(TESTING=True)
    return app.test_client()


def test_listing_links_to_detail_and_current_game_separately(app_client):
    page = app_client.get('/compare?before=0288&after=0289').get_data(as_text=True)
    assert 'href="/compare/machine/xevious?before=0288&amp;after=0289"' in page
    assert 'href="/game/xevious"' in page


def test_detail_page_contains_fields_and_trivia(app_client):
    response = app_client.get('/compare/machine/xevious?before=0288&after=0289')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'previous' in html and 'updated' in html
    assert 'TRIVIA - SECTION MODIFIED' in html
    assert '/game/xevious' in html


def test_nonaffected_machine_404(app_client):
    assert app_client.get('/compare/machine/notthere?before=0288&after=0289').status_code == 404


def test_bad_pair_does_not_read_machine(monkeypatch, app_client):
    monkeypatch.setattr(detail, '_load_release', lambda *a: pytest.fail('invalid pair read data'))
    html = app_client.get('/compare/machine/xevious?before=0289&after=0288').get_data(as_text=True)
    assert 'earlier release must precede' in html


def test_source_text_escaped(monkeypatch, app_client):
    monkeypatch.setattr(detail, 'detail_for_machine', lambda *a: '<script>alert(1)</script>')
    html = app_client.get('/compare/machine/xevious?before=0288&after=0289').get_data(as_text=True)
    assert '&lt;script&gt;' in html
    assert '<script>alert(1)</script>' not in html
