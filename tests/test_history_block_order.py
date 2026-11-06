"""Regression tests for GH block ordering."""

from mht.inputs.history_blocks import process_section_blocks


def parse_blocks(lines, section="scoring"):
    """Parse sample GH lines without release artefacts."""
    return process_section_blocks(
        primary="test",
        section_tag=section,
        lines=lines,
        parsing_state={},
    )


def test_bullet_before_following_paragraph():
    """A following paragraph must not precede its bullet."""
    lines = [
        "* First instruction.",
        "* Second instruction.",
        "Additional explanation.",
    ]

    blocks = parse_blocks(lines)

    assert [block["type"] for block in blocks] == [
        "bullet_list",
        "paragraph",
    ]

    assert blocks[0]["items"] == [
        "First instruction.",
        "Second instruction.",
    ]

    assert blocks[1]["text"] == "Additional explanation."


def test_paragraph_list_paragraph_order():
    """Multiple block types must retain their source order."""
    lines = [
        "Opening explanation.",
        "* First instruction.",
        "* Second instruction.",
        "Closing explanation.",
    ]

    blocks = parse_blocks(lines)

    assert [block["type"] for block in blocks] == [
        "paragraph",
        "bullet_list",
        "paragraph",
    ]


def test_numbered_list_before_following_paragraph():
    """Numbered lists must also retain their source order."""
    lines = [
        "1) First step.",
        "2) Second step.",
        "Additional explanation.",
    ]

    blocks = parse_blocks(lines)

    assert [block["type"] for block in blocks] == [
        "numbered_list",
        "paragraph",
    ]


def test_list_separated_from_paragraph_by_blank_line():
    """Blank lines should preserve distinct block boundaries."""
    lines = [
        "* First instruction.",
        "* Second instruction.",
        "",
        "Separate explanation.",
    ]

    blocks = parse_blocks(lines)

    assert [block["type"] for block in blocks] == [
        "bullet_list",
        "paragraph",
    ]


def test_block_positions_follow_source_order():
    """Provenance positions should increase through the output."""
    lines = [
        "Opening explanation.",
        "* First instruction.",
        "* Second instruction.",
        "Closing explanation.",
    ]

    blocks = parse_blocks(lines)

    positions = [
        block["meta"]["filtered_line_start"]
        for block in blocks
    ]

    assert positions == sorted(positions)
