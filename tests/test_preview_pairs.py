"""Regression tests for GH pair rendering in the web preview."""

from pathlib import Path

import pytest
from flask import Flask, render_template


@pytest.fixture
def app():
    """Create a minimal Flask app using the real preview templates."""

    template_dir = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "mht"
        / "preview"
        / "templates"
    )

    app = Flask(__name__, template_folder=str(template_dir))

    # Routes required by game.html and its parent template.
    app.add_url_rule("/", endpoint="home", view_func=lambda: "")
    app.add_url_rule(
        "/game/<machine>",
        endpoint="game",
        view_func=lambda machine: "",
    )
    app.add_url_rule(
        "/search",
        endpoint="search",
        view_func=lambda: "",
    )
    app.add_url_rule(
        "/catalogue",
        endpoint="catalogue",
        view_func=lambda: "",
    )
    app.add_url_rule(
        "/diagnostics",
        endpoint="diagnostics",
        view_func=lambda: "",
    )
    app.add_url_rule(
        "/compare",
        endpoint="release_comparison",
        view_func=lambda: "",
    )

    return app


def render_game(app, *, overview_blocks=None, trivia_sections=None):
    """Render the real game template with representative GH blocks."""

    with app.test_request_context("/game/mk"):
        return render_template(
            "game.html",
            wiki_page_name="Mortal Kombat",
            opening_sentence="Test introduction.",
            prev_machine="mk",
            next_machine="mk",
            overview_blocks=overview_blocks or [],
            trivia_sections=trivia_sections or [],
            mame_titles_display=[],
            ports_display={},
            record={},
        )


def test_overview_pair_is_visible(app):
    blocks = [
        {
            "type": "pair",
            "label": "Game ID",
            "value": "Example-001",
        }
    ]

    html = render_game(app, overview_blocks=blocks)

    assert "<dt>Game ID</dt>" in html
    assert "<dd>Example-001</dd>" in html


def test_scoring_pair_is_visible(app):
    sections = [
        {
            "name": "scoring",
            "blocks": [
                {
                    "type": "pair",
                    "label": "High Punch",
                    "value": "500 points",
                }
            ],
        }
    ]

    html = render_game(app, trivia_sections=sections)

    assert "<dt>High Punch</dt>" in html
    assert "<dd>500 points</dd>" in html


def test_multiple_staff_pairs_are_preserved(app):
    sections = [
        {
            "name": "staff",
            "blocks": [
                {
                    "type": "pair",
                    "label": "Design and software",
                    "value": "Ed Boon",
                },
                {
                    "type": "pair",
                    "label": "Design and graphics",
                    "value": "John Tobias",
                },
                {
                    "type": "pair",
                    "label": "Music and sounds",
                    "value": "Dan Forden",
                },
            ],
        }
    ]

    html = render_game(app, trivia_sections=sections)

    expected_pairs = [
        ("Design and software", "Ed Boon"),
        ("Design and graphics", "John Tobias"),
        ("Music and sounds", "Dan Forden"),
    ]

    for label, value in expected_pairs:
        assert f"<dt>{label}</dt>" in html
        assert f"<dd>{value}</dd>" in html

    assert html.count("<dt>") == 3
    assert html.count("<dd>") == 3
