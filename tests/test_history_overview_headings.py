"""Regression tests for implicit GH Overview subheadings."""

from mht.inputs.history_blocks import process_section_blocks


def parse_overview(lines):
    """Classify Overview lines using the production block parser."""
    return process_section_blocks(
        primary="test",
        section_tag="overview",
        lines=lines,
        parsing_state={},
    )


def test_heading_without_terminal_punctuation():
    """A short marked title can introduce an Overview description."""
    blocks = parse_overview([
        "",
        "* New Controls",
        "Players controls consist of a rotary controller.",
        "",
    ])

    assert [block["type"] for block in blocks] == [
        "subheading",
        "paragraph",
    ]

    assert blocks[0]["text"] == "New Controls"


def test_heading_with_full_stop():
    """A full stop does not necessarily make a title a bullet."""
    blocks = parse_overview([
        "",
        "* More Visual and Audio Entertainment.",
        '720° has a new 25" higher-resolution monitor for better graphics.',
        "",
    ])

    assert [block["type"] for block in blocks] == [
        "subheading",
        "paragraph",
    ]


def test_heading_followed_by_multiple_description_lines():
    """A heading can introduce more than one descriptive source line."""
    blocks = parse_overview([
        "",
        "* Operator Features",
        "The machine includes a comprehensive self-test system.",
        "Additional difficulty settings are available.",
        "",
    ])

    assert blocks[0]["type"] == "subheading"
    assert [
        block["type"]
        for block in blocks[1:]
    ] == [
        "paragraph",
        "paragraph",
    ]


def test_long_bullet_remains_a_bullet():
    """A substantial marked description must not become a heading."""
    blocks = parse_overview([
        "",
        (
            "* Double Breakout: before serving the ball, "
            "the playfield contains 52 orange bricks "
            "and 52 green bricks beneath them."
        ),
        "Two paddles are displayed at the bottom of the screen.",
        "",
    ])

    assert blocks[0]["type"] == "bullet_list"


def test_short_bullet_without_description_remains_a_bullet():
    """A standalone list entry must not become a heading."""
    blocks = parse_overview([
        "* Extra life awarded at 10000 points.",
        "",
    ])

    assert blocks[0]["type"] == "bullet_list"
