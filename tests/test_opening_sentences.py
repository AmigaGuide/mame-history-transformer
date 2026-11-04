import pytest

from mht.transform.opening_sentences import build_opening_sentence


def test_standard_arcade_game():
    sentence = build_opening_sentence(
        title="Out Run",
        genre_phrase="a chase-view racing arcade video game",
        year="1986",
        manufacturer="Sega",
    )

    assert sentence == (
        "Out Run is a chase-view racing arcade video game "
        "published in 1986 by Sega."
    )


def test_laserdisc_game():
    sentence = build_opening_sentence(
        title="Road Blaster",
        genre_phrase="a reaction-based driving arcade video game",
        year="1985",
        manufacturer="Data East",
        laserdisc=True,
    )

    assert sentence == (
        "Road Blaster is an interactive reaction-based driving "
        "arcade video game published in 1985 by Data East."
    )


def test_vector_graphics_game():
    sentence = build_opening_sentence(
        title="Star Wars",
        genre_phrase=(
            "a first-person flight-based shooting action arcade video game"
        ),
        year="1983",
        manufacturer="Atari",
        vector=True,
    )

    assert sentence == (
        "Star Wars is a first-person flight-based shooting action "
        "arcade video game featuring vector graphics, "
        "published in 1983 by Atari."
    )


def test_both_technical_modifiers():
    sentence = build_opening_sentence(
        title="Example Game",
        genre_phrase="a shooting arcade video game",
        year="1984",
        manufacturer="Example Company",
        laserdisc=True,
        vector=True,
    )

    assert sentence == (
        "Example Game is an interactive shooting arcade video game "
        "featuring vector graphics, published in 1984 by Example Company."
    )


def test_year_without_manufacturer():
    sentence = build_opening_sentence(
        title="Example Game",
        genre_phrase="a puzzle arcade video game",
        year="1982",
    )

    assert sentence == (
        "Example Game is a puzzle arcade video game published in 1982."
    )


def test_manufacturer_without_year():
    sentence = build_opening_sentence(
        title="Example Game",
        genre_phrase="a puzzle arcade video game",
        manufacturer="Example Company",
    )

    assert sentence == (
        "Example Game is a puzzle arcade video game "
        "published by Example Company."
    )


def test_missing_publication_information():
    sentence = build_opening_sentence(
        title="Example Game",
        genre_phrase="a puzzle arcade video game",
    )

    assert sentence == (
        "Example Game is a puzzle arcade video game."
    )


def test_vector_without_publication_information():
    sentence = build_opening_sentence(
        title="Example Game",
        genre_phrase="a shooting arcade video game",
        vector=True,
    )

    assert sentence == (
        "Example Game is a shooting arcade video game "
        "featuring vector graphics."
    )


def test_existing_an_article_is_preserved():
    sentence = build_opening_sentence(
        title="Example Game",
        genre_phrase="an American football arcade video game",
    )

    assert sentence == (
        "Example Game is an American football arcade video game."
    )


def test_missing_title_is_rejected():
    with pytest.raises(ValueError, match="game title"):
        build_opening_sentence(
            title="",
            genre_phrase="a puzzle arcade video game",
        )


def test_missing_approved_phrase_is_rejected():
    with pytest.raises(ValueError, match="approved genre phrase"):
        build_opening_sentence(
            title="Example Game",
            genre_phrase="",
        )
