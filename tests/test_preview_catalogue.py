"""Phase 5 regression coverage for previewing systems without wiki ports."""
from __future__ import annotations

import json

import pytest

from mht.preview.app import create_app
from mht.preview.loaders import load_preview_data
from mht.preview.preview_data import PreviewData


def _preview_data():
    return PreviewData(
        wiki_doc={"games": {"pacman": {"wiki_page_name": "Pac-Man"}}},
        wiki_games={"pacman": {"wiki_page_name": "Pac-Man", "year": "1980"}},
        trivia_by_machine={
            "afm_113": {
                "sections": {
                    "overview": {"blocks": [{"type": "paragraph", "text": "Pinball overview text."}]},
                    "technical": {"blocks": [{"type": "paragraph", "text": "Pinball technical trivia."}]},
                }
            },
            "pacman": {"sections": {}},
            "orphan_trivia": {"sections": {"overview": {"blocks": [{"type": "paragraph", "text": "Standalone GH text."}]}}},
        },
        mame_machines={
            "afm_113": {"description": "Attack from Mars", "year": "1995", "manufacturer": "Bally"},
            "pacman": {"description": "Pac-Man", "year": "1980", "manufacturer": "Namco"},
            "unrelated_device": {"description": "Device"},
        },
        mame_summary={}, history_summary={}, ini_summary={}, transform_summary={},
        machine_order=["afm_113", "orphan_trivia", "pacman"],
    )


@pytest.fixture
def client():
    app = create_app(_preview_data(), version="0289")
    app.config.update(TESTING=True)
    return app.test_client()


def test_trivia_without_published_ports_opens_game_page(client):
    response = client.get("/game/afm_113")
    assert response.status_code == 200
    assert b"Attack from Mars" in response.data
    assert b"Pinball overview text." in response.data
    assert b"Pinball technical trivia." in response.data
    assert b"not included in the ExoticA wiki output" in response.data


def test_published_game_still_renders_without_unpublished_note(client):
    response = client.get("/game/pacman")
    assert response.status_code == 200
    assert b"Pac-Man" in response.data
    assert b"not included in the ExoticA wiki output" not in response.data


def test_search_finds_trivia_only_machine(client):
    response = client.get("/search?q=afm")
    assert response.status_code == 200
    assert b"afm_113" in response.data
    assert b"Attack from Mars" in response.data
    assert b"1995" in response.data


def test_non_catalogue_mame_device_remains_unlisted(client):
    assert client.get("/game/unrelated_device").status_code == 404
    assert b"No results." in client.get("/search?q=unrelated_device").data


def test_trivia_without_mame_metadata_uses_machine_name(client):
    response = client.get("/game/orphan_trivia")
    assert response.status_code == 200
    assert b"Standalone GH text." in response.data
    assert b"orphan_trivia" in response.data


def test_home_retains_published_count_and_shows_preview_count(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Total games in wiki output: 1" in response.data
    assert b"Games available for preview: 3" in response.data


def test_loader_builds_union_of_wiki_and_trivia(monkeypatch):
    from mht.preview import loaders

    documents = {
        "Exotica wiki data": {"games": {"pacman": {"wiki_page_name": "Pac-Man"}}},
        "GH system trivia": {
            "afm_113": {"sections": {"overview": {"blocks": []}}},
            "pacman": {"sections": {}},
        },
        "MAME machines": {"afm_113": {"description": "Attack from Mars"}, "otherdevice": {}},
        "MAME parsing summary": {},
        "History parsing summary": {},
        "INI parsing summary": {},
        "Transform summary": {},
    }
    def fake_load_json(path, label):
        return documents[label]

    monkeypatch.setattr(loaders, "load_json", fake_load_json)
    preview = load_preview_data(version="0289")
    assert preview.machine_order == ["afm_113", "pacman"]
    assert "afm_113" not in preview.wiki_games
    assert "otherdevice" not in preview.machine_order
