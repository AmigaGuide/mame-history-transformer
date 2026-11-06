"""Regression tests for named topics within GH Overview sections."""

from mht.inputs.history_blocks import process_section_blocks


def parse_overview(lines):
    """Classify Overview source lines using the production parser."""
    return process_section_blocks(
        primary="test",
        section_tag="overview",
        lines=lines,
        parsing_state={},
    )


def test_repeated_named_topics_with_descriptions():
    """
    An introductory paragraph and repeated marked topic groups
    provide evidence that the markers represent subheadings.

    Each heading shares its source line with its initial description.
    Additional unmarked lines remain separate paragraphs.
    """
    lines = [
        "The three available Super Breakout modes are the following:",
        "",
        "* Double Breakout: before serving the ball, two brick walls appear.",
        "Two paddles are displayed at the bottom of the screen.",
        "",
        "* Cavity Breakout: before serving the ball, captive balls appear.",
        "One paddle is provided in this game.",
        "",
        "* Progressive Breakout: before serving the ball, walls scroll.",
        "The brick walls move toward the paddle.",
        "As the walls scroll down, their colours change.",
    ]

    blocks = parse_overview(lines)

    assert [block["type"] for block in blocks] == [
        "paragraph",
        "subheading",
        "paragraph",
        "paragraph",
        "subheading",
        "paragraph",
        "paragraph",
        "subheading",
        "paragraph",
        "paragraph",
        "paragraph",
    ]

    assert blocks[0]["text"] == (
        "The three available Super Breakout modes are the following:"
    )

    assert [
        block["text"]
        for block in blocks
        if block["type"] == "subheading"
    ] == [
        "Double Breakout",
        "Cavity Breakout",
        "Progressive Breakout",
    ]

    assert blocks[2]["text"] == (
        "Before serving the ball, two brick walls appear."
    )

    assert blocks[5]["text"] == (
        "Before serving the ball, captive balls appear."
    )

    assert blocks[8]["text"] == (
        "Before serving the ball, walls scroll."
    )


def test_named_topic_preserves_source_line_provenance():
    """
    A heading and its initial description originate on the same
    physical source line, even though they become separate blocks.
    """
    lines = [
        "The available modes are:",
        "",
        "* Double Breakout: before serving the ball, bricks appear.",
        "Two paddles are displayed.",
        "",
        "* Cavity Breakout: before serving the ball, balls appear.",
        "One paddle is provided.",
    ]

    blocks = parse_overview(lines)

    heading = blocks[1]
    description = blocks[2]

    assert heading["type"] == "subheading"
    assert description["type"] == "paragraph"

    assert heading["meta"]["filtered_line_start"] == 2
    assert heading["meta"]["filtered_line_end"] == 2

    assert description["meta"]["filtered_line_start"] == 2
    assert description["meta"]["filtered_line_end"] == 2


def test_isolated_marked_colon_entry_remains_a_bullet():
    """
    A colon alone is insufficient evidence of a named-topic group.
    A conventional marked entry must not be promoted automatically.
    """
    blocks = parse_overview([
        "* Bonus points: collect the hidden treasure.",
        "",
        "The next stage begins after the timer expires.",
    ])

    assert blocks[0]["type"] == "bullet_list"
    assert blocks[0]["items"] == [
        "Bonus points: collect the hidden treasure."
    ]
