from mht.utils.wiki_pages import compute_pages_and_redirects


PREFIX = "Lost In Translation/"


def test_canonical_page_wins_over_redirect():
    records = {
        "aof": {
            "wiki_page_name": "Art of Fighting",
            "wiki_redirects": [],
        },
        "aof3": {
            "wiki_page_name": (
                "Art of Fighting 3: The Path of the Warrior"
            ),
            "wiki_redirects": [
                "Art of Fighting",
                "Art of Fighting: Ryuuko no Ken Gaiden",
                "Art of Fighting 3",
            ],
        },
    }

    result = compute_pages_and_redirects(records, PREFIX)

    assert PREFIX + "Art of Fighting" not in result["redirects"]

    assert result["redirects"][
        PREFIX + "Art of Fighting: Ryuuko no Ken Gaiden"
    ] == PREFIX + "Art of Fighting 3: The Path of the Warrior"

    collisions = result["conflicts"]["redirect_page_collisions"]

    assert collisions == [{
        "name": PREFIX + "Art of Fighting",
        "canonical_machines": ["aof"],
        "candidates": [{
            "machine": "aof3",
            "target": (
                PREFIX
                + "Art of Fighting 3: The Path of the Warrior"
            ),
        }],
        "disambiguation_candidate": True,
    }]

    assert "Art of Fighting" in records["aof3"]["wiki_redirects"]


def test_multiple_candidates_are_preserved():
    records = {
        "starwars": {
            "wiki_page_name": "Star Wars",
            "wiki_redirects": [],
        },
        "swracer": {
            "wiki_page_name": "Star Wars: Racer Arcade",
            "wiki_redirects": ["Star Wars"],
        },
        "other": {
            "wiki_page_name": "Another Star Wars Game",
            "wiki_redirects": ["star wars"],
        },
    }

    result = compute_pages_and_redirects(records, PREFIX)
    collisions = result["conflicts"]["redirect_page_collisions"]

    assert result["stats"]["redirect_page_collisions"] == 1
    assert len(collisions) == 1
    assert collisions[0]["canonical_machines"] == ["starwars"]
    assert {item["machine"] for item in collisions[0]["candidates"]} == {
        "swracer", "other"
    }


def test_unambiguous_redirect_still_works():
    records = {
        "pang3": {
            "wiki_page_name": "Pang! 3",
            "wiki_redirects": [
                "Pang! 3: Kaitou Tachi no Karei na Gogo"
            ],
        },
    }

    result = compute_pages_and_redirects(records, PREFIX)

    assert result["redirects"][
        PREFIX + "Pang! 3: Kaitou Tachi no Karei na Gogo"
    ] == PREFIX + "Pang! 3"

    assert result["conflicts"]["redirect_page_collisions"] == []


def test_canonical_name_does_not_redirect_to_itself():
    records = {
        "scontra": {
            "wiki_page_name": "Super Contra",
            "wiki_redirects": ["Super Contra", "Alternative Contra"],
        },
    }

    result = compute_pages_and_redirects(records, PREFIX)

    assert PREFIX + "Super Contra" not in result["redirects"]
    assert result["redirects"][
        PREFIX + "Alternative Contra"
    ] == PREFIX + "Super Contra"
    assert result["conflicts"]["redirect_page_collisions"] == []
