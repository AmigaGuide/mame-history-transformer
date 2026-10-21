from mht.utils.wiki_pages import compute_pages_and_redirects


def test_page_and_redirect_conflict_counts():
    records = {
        "game_a": {
            "wiki_page_name": "Shared Title",
            "wiki_redirects": ["Common Redirect"],
        },
        "game_b": {
            "wiki_page_name": "Shared Title",
            "wiki_redirects": [],
        },
        "game_c": {
            "wiki_page_name": "Different Title",
            "wiki_redirects": ["Common Redirect"],
        },
    }

    result = compute_pages_and_redirects(
        records,
        prefix="Lost In Translation/",
    )

    stats = result["stats"]
    conflicts = result["conflicts"]

    assert stats["parents_total"] == 3
    assert stats["page_names_total"] == 2
    assert stats["redirects_total"] == 1

    assert stats["page_name_collisions"] == 1
    assert stats["redirect_conflicts"] == 1

    total_conflicts = (
        stats["page_name_collisions"]
        + stats["redirect_conflicts"]
    )

    assert total_conflicts == 2

    assert len(conflicts["page_name_collisions"]) == 1
    assert len(conflicts["redirect_conflicts"]) == 1
