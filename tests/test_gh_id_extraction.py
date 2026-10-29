import pytest

from mht.inputs.history_text import parse_gh_id_from_contribute


@pytest.mark.parametrize(
    "url, expected",
    [
        (
            "https://www.arcade-history.com/?&page=detail&id=83855&o=2",
            83855,
        ),
        (
            "https://www.arcade-history.com/?&amp;page=detail&amp;id=83855&amp;o=2",
            83855,
        ),
        (
            "https://www.arcade-history.com/game/83855/?o=2",
            83855,
        ),
        (
            "https://www.arcade-history.com/game/83855/",
            83855,
        ),
        (
            "https://www.arcade-history.com/game/83855/?o=2</text>",
            83855,
        ),
        (
            "https://www.arcade-history.com/",
            None,
        ),
    ],
)
def test_gh_id_extraction(url, expected):
    lines = [f"Edit this entry: {url}"]

    assert parse_gh_id_from_contribute(lines) == expected
