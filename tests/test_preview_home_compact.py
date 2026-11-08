"""Phase 9B: compact landing page and common Diagnostics navigation."""
from __future__ import annotations

import pytest

from mht.preview.app import create_app
from mht.preview.preview_data import PreviewData


def make_data():
    return PreviewData(
        wiki_doc={"games": {"pacman": {"wiki_page_name": "Pac-Man"}}},
        wiki_games={"pacman": {"wiki_page_name": "Pac-Man"}},
        trivia_by_machine={"afm_113": {"sections": {}}},
        mame_machines={"pacman": {"description": "Pac-Man"}},
        mame_summary={
            "header": {"versions": {"mame_build": "0.289 (mame0289)"}},
            "provenance": {"inputs": [{"zip_archive": "mame0289.zip", "zip_member": "mame.xml"}]},
            "totals": {"total_machines": 50368},
        },
        history_summary={
            "header": {"versions": {"gh_version": "2.89", "gh_date": "2026-08-07"}},
            "totals": {"systems_total": 18550},
        },
        ini_summary={"ini": {"files": {}}},
        transform_summary={"counts": {"final_included": 1629}},
        machine_order=["afm_113", "pacman"],
    )


@pytest.fixture
def client():
    app = create_app(make_data(), version="0289")
    app.config.update(TESTING=True)
    return app.test_client()


def test_home_keeps_four_stage_headings(client):
    html = client.get('/').get_data(as_text=True)
    assert html.count('class="overview-cell"') == 4
    for title in ('MAME XML', 'Gaming History XML', 'Gaming History INIs', 'Transformation'):
        assert title in html


def test_home_displays_release_counts_and_provenance(client):
    html = client.get('/').get_data(as_text=True)
    assert 'Release 0289 at a glance' in html
    assert 'Games in ExoticA wiki output' in html
    assert 'Entries available for preview' in html
    assert 'mame0289.zip' in html
    assert '50,368' not in html  # Existing numeric formatting remains unchanged.
    assert '50368' in html


def test_home_retains_all_four_summary_destinations(client):
    html = client.get('/').get_data(as_text=True)
    for target in ('/summary/mame', '/summary/history', '/summary/ini', '/summary/transform'):
        assert f'href="{target}"' in html


def test_home_has_catalogue_and_diagnostics_links(client):
    html = client.get('/').get_data(as_text=True)
    assert 'href="/catalogue"' in html
    assert 'href="/diagnostics"' in html


def test_home_does_not_repeat_detailed_distributions(client):
    html = client.get('/').get_data(as_text=True)
    assert 'Top display types' not in html
    assert 'Trivia blocks by type' not in html
    assert 'Excluded by reason (top 5)' not in html


def test_diagnostics_link_is_shared_across_pages(client):
    for url in ('/', '/catalogue', '/game/pacman', '/diagnostics'):
        resp = client.get(url)
        assert resp.status_code == 200
        assert b'href="/diagnostics"' in resp.data


def test_missing_transform_count_is_not_assumed_zero():
    data = make_data()
    # Ensure the unknown fallback is not silently treated as zero.
    from dataclasses import replace
    app = create_app(replace(data, transform_summary={}), version='0289')
    app.config.update(TESTING=True)
    html = app.test_client().get('/').get_data(as_text=True)
    assert 'Final included parents: unknown' in html
