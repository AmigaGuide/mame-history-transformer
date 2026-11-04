from mht.utils.records import project_for_wiki


def test_wiki_projection_preserves_opening_sentence():
    sentence = (
        "Star Wars is a first-person flight-based shooting action "
        "arcade video game featuring vector graphics, "
        "published in 1983 by Atari."
    )

    record = {
        "wiki_page_name": "Star Wars",
        "opening_sentence": sentence,
        "year": "1983",
        "manufacturer": "Atari",
    }

    wiki = project_for_wiki(record)

    assert wiki["opening_sentence"] == sentence
    assert wiki["wiki_page_name"] == "Star Wars"


def test_laserdisc_sentence_survives_projection():
    sentence = (
        "Road Blaster is an interactive reaction-based driving "
        "arcade video game published in 1985 by Data East."
    )

    record = {
        "wiki_page_name": "Road Blaster",
        "opening_sentence": sentence,
    }

    wiki = project_for_wiki(record)

    assert wiki["opening_sentence"] == sentence


def test_raw_projection_excludes_opening_sentence():
    from mht.utils.records import project_for_raw

    record = {
        "wiki_page_name": "Star Wars",
        "opening_sentence": (
            "Star Wars is a vector graphics arcade video game."
        ),
    }

    raw = project_for_raw("starwars", record)

    assert "opening_sentence" not in raw
