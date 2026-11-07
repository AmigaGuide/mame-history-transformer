"""Regression tests for the read-only preview catalogue filters."""
from __future__ import annotations

from mht.preview.app import create_app
from mht.preview.catalogue import PAGE_SIZE, select_catalogue_page
from mht.preview.preview_data import PreviewData


def sample_data():
    return PreviewData(
        wiki_doc={"games": {}},
        wiki_games={
            "pacman": {"wiki_page_name": "Pac-Man", "year": "1980"},
            "galaga": {"wiki_page_name": "Galaga"},
        },
        trivia_by_machine={
            "afm_113": {"sections": {"technical": {"blocks": []}}},
            "pacman": {"sections": {}},
        },
        mame_machines={
            "pacman": {"description": "Pac-Man", "manufacturer": "Namco"},
            "afm_113": {"description": "Attack from Mars", "year": "1995"},
            "galaga": {"description": "Galaga"},
        },
        mame_summary={}, history_summary={}, ini_summary={}, transform_summary={},
        machine_order=["afm_113", "galaga", "pacman"],
    )


def test_all_catalogue_entries():
    result = select_catalogue_page(sample_data())
    assert result["total_results"] == 3
    assert [r["machine"] for r in result["results"]] == ["afm_113", "galaga", "pacman"]


def test_published_filter():
    result = select_catalogue_page(sample_data(), status="published")
    assert [r["machine"] for r in result["results"]] == ["galaga", "pacman"]


def test_trivia_only_filter():
    result = select_catalogue_page(sample_data(), status="trivia-only")
    assert [r["machine"] for r in result["results"]] == ["afm_113"]


def test_gh_record_present_includes_empty_sections():
    result = select_catalogue_page(sample_data(), trivia="yes")
    assert [r["machine"] for r in result["results"]] == ["afm_113", "pacman"]


def test_gh_record_absent():
    result = select_catalogue_page(sample_data(), trivia="no")
    assert [r["machine"] for r in result["results"]] == ["galaga"]


def test_combined_filters():
    result = select_catalogue_page(sample_data(), status="published", trivia="yes")
    assert [r["machine"] for r in result["results"]] == ["pacman"]


def test_description_case_insensitive_search():
    result = select_catalogue_page(sample_data(), query="ATTACK FROM")
    assert [r["machine"] for r in result["results"]] == ["afm_113"]


def test_unknown_filter_falls_back_to_all():
    result = select_catalogue_page(sample_data(), status="garbage", trivia="garbage")
    assert result["total_results"] == 3
    assert result["status"] == "all" and result["trivia"] == "any"


def test_pagination_limits_and_clamps():
    data = sample_data()
    data.machine_order[:] = [f"m{i:03d}" for i in range(PAGE_SIZE + 3)]
    data.mame_machines.update({m: {"description": m} for m in data.machine_order})
    first = select_catalogue_page(data, page="bad")
    last = select_catalogue_page(data, page="999")
    assert len(first["results"]) == PAGE_SIZE
    assert first["page"] == 1
    assert last["page"] == 2
    assert len(last["results"]) == 3


def test_catalogue_route_and_links():
    app = create_app(sample_data(), version="0289")
    app.config.update(TESTING=True)
    client = app.test_client()
    response = client.get("/catalogue?status=trivia-only")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "afm_113" in text
    assert "pacman</a>" not in text
    assert 'value="trivia-only" selected' in text
    assert "Catalogue" in client.get("/").get_data(as_text=True)


def test_existing_search_unchanged():
    app = create_app(sample_data(), version="0289")
    app.config.update(TESTING=True)
    text = app.test_client().get("/search?q=afm").get_data(as_text=True)
    assert "afm_113" in text


def test_no_matches_is_not_an_error():
    app = create_app(sample_data(), version="0289")
    app.config.update(TESTING=True)
    response = app.test_client().get("/catalogue?q=nothingmatches")
    assert response.status_code == 200
    assert "No entries match these filters." in response.get_data(as_text=True)
