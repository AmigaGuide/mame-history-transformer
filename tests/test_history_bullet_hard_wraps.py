"""Regression tests for hard-wrapped GH bullet entries."""

from mht.inputs.history_blocks import process_section_blocks


def parse_blocks(lines, section="scoring"):
    """Classify GH source lines without reading release artefacts."""
    return process_section_blocks(
        primary="test",
        section_tag=section,
        lines=lines,
        parsing_state={},
    )


def test_bullet_continuation_after_preposition():
    """An unfinished bullet should absorb its continuation line."""
    lines = [
        "* You need 17 or more bubbles.",
        "* One of these bubbles must touch exactly one bubble of a group of",
        "similarly colored bubbles.",
    ]

    blocks = parse_blocks(lines)

    assert [block["type"] for block in blocks] == [
        "bullet_list",
    ]

    assert blocks[0]["items"] == [
        "You need 17 or more bubbles.",
        (
            "One of these bubbles must touch exactly one "
            "bubble of a group of similarly colored bubbles."
        ),
    ]

    # Two list items occupy three physical source lines.
    assert blocks[0]["meta"]["filtered_line_start"] == 0
    assert blocks[0]["meta"]["filtered_line_end"] == 2

    # The list contains two items spanning three physical lines.
    assert blocks[0]["meta"]["filtered_line_start"] == 0
    assert blocks[0]["meta"]["filtered_line_end"] == 2


def test_bullet_continuation_after_auxiliary_verb():
    """A bullet ending in 'must' should retain the following text."""
    lines = [
        "* The bubble that pops the similarly colored group of bubbles must",
        "not touch the group of 17 or more bubbles.",
    ]

    blocks = parse_blocks(lines)

    assert blocks[0]["type"] == "bullet_list"
    assert blocks[0]["items"] == [
        (
            "The bubble that pops the similarly colored "
            "group of bubbles must not touch the group "
            "of 17 or more bubbles."
        )
    ]


def test_complete_bullet_keeps_separate_explanation():
    """A complete bullet followed by prose remains separate."""
    lines = [
        "* Passing through Gates. The player receives points.",
        "If a player swishes a gate, the multiplier increases.",
    ]

    blocks = parse_blocks(lines)

    assert [block["type"] for block in blocks] == [
        "bullet_list",
        "paragraph",
    ]


def test_blank_line_prevents_continuation():
    """A blank line separates a bullet from subsequent narrative."""
    lines = [
        "* The player receives bonus points",
        "",
        "Additional scoring information.",
    ]

    blocks = parse_blocks(lines)

    assert [block["type"] for block in blocks] == [
        "bullet_list",
        "paragraph",
    ]


def test_explicit_subheading_remains_separate():
    """Explicit colon headings must not absorb their descriptions."""
    lines = [
        "* How to Play:",
        "Control airplane with 8-way joystick.",
    ]

    blocks = parse_blocks(lines, section="tips and tricks")

    assert [block["type"] for block in blocks] == [
        "subheading",
        "paragraph",
    ]


def test_multiple_continuation_lines_preserve_provenance():
    """A bullet can span several physical source lines."""
    lines = [
        "* The player must collect all of the",
        "remaining coloured bubbles before",
        "moving to the next stage.",
    ]

    blocks = parse_blocks(lines)

    assert len(blocks) == 1
    assert blocks[0]["type"] == "bullet_list"

    assert blocks[0]["items"] == [
        (
            "The player must collect all of the "
            "remaining coloured bubbles before "
            "moving to the next stage."
        )
    ]

    meta = blocks[0]["meta"]

    assert meta["filtered_line_start"] == 0
    assert meta["filtered_line_end"] == 2
