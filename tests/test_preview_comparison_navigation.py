"""Phase 13: preserve the affected-machine browsing context on detail navigation."""
from __future__ import annotations

import pytest

from mht.preview import release_comparison as comparison
from mht.preview import machine_detail as detail
from mht.preview.app import create_app
from mht.preview.preview_data import PreviewData


def make_data():
    return PreviewData(
        wiki_doc={}, wiki_games={}, trivia_by_machine={}, mame_machines={},
        mame_summary={}, history_summary={}, ini_summary={}, transform_summary={},
        machine_order=['xevious'],
    )


@pytest.fixture
def client(monkeypatch):
    affected = {
        'xevious': {
            'status': 'modified', 'page_before': 'Xevious', 'page_after': 'Xevious',
            'wiki_regions': [], 'trivia_sections': ['trivia'],
        }
    }
    monkeypatch.setattr(comparison, 'available_releases', lambda: ['0288', '0289'])
    monkeypatch.setattr(comparison, 'compare_release_content', lambda *args: {
        'counts': {'affected_machines': 1}, 'scope': 'Generated data',
        'renamed': [], 'affected_region_counts': {'GH Trivia: trivia': 1},
        'affected': affected, 'modified': {},
    })
    monkeypatch.setattr(detail, 'detail_for_machine', lambda *args: 'TRIVIA MODIFIED')
    app = create_app(make_data(), version='0289')
    app.config.update(TESTING=True)
    return app.test_client()


def test_filtered_list_link_preserves_query_and_page(client):
    html = client.get('/compare?before=0288&after=0289&q=xev&status=modified&change=trivia&page=2').get_data(as_text=True)
    # The synthetic report has only one affected record: page 2 clamps to page 1.
    assert '/compare/machine/xevious?before=0288&amp;after=0289&amp;q=xev&amp;status=modified&amp;change=trivia&amp;page=1' in html
    assert 'id="affected-machines"' in html
    assert 'href="#affected-machines"' in html


def test_detail_back_link_restores_filters_and_anchor(client):
    url = '/compare/machine/xevious?before=0288&after=0289&q=xev&status=modified&change=trivia&page=1'
    html = client.get(url).get_data(as_text=True)
    expected = '/compare?before=0288&amp;after=0289&amp;q=xev&amp;status=modified&amp;change=trivia&amp;page=1#affected-machines'
    assert html.count('href="' + expected + '"') == 2
    assert 'TRIVIA MODIFIED' in html


def test_unfiltered_detail_returns_to_machine_section(client):
    html = client.get('/compare/machine/xevious?before=0288&after=0289').get_data(as_text=True)
    assert '/compare?before=0288&amp;after=0289#affected-machines' in html


def test_invalid_release_context_still_has_safe_return_link(client):
    response = client.get('/compare/machine/xevious?before=0289&after=0288&status=renamed')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'earlier release must precede' in html
    assert '/compare?before=0289&amp;after=0288&amp;status=renamed#affected-machines' in html


def test_query_is_html_escaped_in_return_link(client):
    html = client.get(
        '/compare/machine/xevious?before=0288&after=0289&q=%3Cscript%3E'
    ).get_data(as_text=True)

    assert 'q=%3Cscript%3E' in html
    assert 'q=<script>' not in html
