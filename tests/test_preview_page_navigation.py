"""Preview presentation regression tests: headings, local navigation and pair layout."""
from __future__ import annotations


import pytest

from mht.preview.app import create_app
from mht.preview.preview_data import PreviewData


@pytest.fixture
def client():
    data = PreviewData(
        wiki_doc={"games": {"pacman": {"wiki_page_name": "Pac-Man"}}},
        wiki_games={"pacman": {"wiki_page_name": "Pac-Man"}},
        trivia_by_machine={
            "afm_113": {
                "sections": {
                    "overview": {"blocks": [{"type": "paragraph", "text": "Overview content."}]},
                    "technical": {"blocks": [{"type": "pair", "label": "Height", "value": "76 inches"}]},
                    "tips_and_tricks": {"blocks": [{"type": "paragraph", "text": "Helpful advice."}]},
                }
            },
            "pacman": {"sections": {}},
        },
        mame_machines={"afm_113": {"description": "Attack from Mars", "year": "1995"}},
        mame_summary={}, history_summary={}, ini_summary={}, transform_summary={},
        machine_order=["afm_113", "pacman"],
    )
    app = create_app(data, version="0289")
    app.config.update(TESTING=True)
    return app.test_client()


def test_readable_section_titles(client):
    html = client.get('/game/afm_113').get_data(as_text=True)
    assert '>Technical</h2>' in html
    assert '>Tips and tricks</h2>' in html
    assert '>technical</h2>' not in html


def test_section_navigation_links_have_matching_targets(client):
    html = client.get('/game/afm_113').get_data(as_text=True)
    for anchor in ('trivia-overview', 'trivia-section-1', 'trivia-section-2'):
        assert f'href="#{anchor}"' in html
        assert f'id="{anchor}"' in html


def test_pair_display_preserves_label_and_value(client):
    html = client.get('/game/afm_113').get_data(as_text=True)
    assert '<dl class="trivia-pair">' in html
    assert '<dt>Height</dt>' in html
    assert '<dd>76 inches</dd>' in html


def test_unpublished_notice_remains_visible(client):
    html = client.get('/game/afm_113').get_data(as_text=True)
    assert 'not included in the ExoticA wiki output' in html


def test_published_game_does_not_display_unpublished_notice(client):
    html = client.get('/game/pacman').get_data(as_text=True)
    assert 'not included in the ExoticA wiki output' not in html


def test_no_trivia_has_no_empty_navigation(client):
    html = client.get('/game/pacman').get_data(as_text=True)
    assert 'class="trivia-toc"' not in html
