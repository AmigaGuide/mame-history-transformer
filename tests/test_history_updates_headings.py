"""Tests for context-aware heading detection in GH Updates sections."""

from mht.inputs.history_blocks import process_section_blocks


def parse_blocks(section, lines):
    """Parse sample GH lines without loading release artefacts."""
    return process_section_blocks(
        primary="test",
        section_tag=section,
        lines=lines,
        parsing_state={},
    )


def test_updates_star_heading_followed_by_dash_list():
    """An asterisk heading introduces a list of revision changes."""
    lines = [
        "* 1.50 (May 5, 2010)",
        "- Fixed the first problem.",
        "- Fixed the second problem.",
        "",
        "* 1.44 (September 2, 2009)",
        "- Fixed another problem.",
    ]

    blocks = parse_blocks("updates", lines)

    assert [block["type"] for block in blocks] == [
        "subheading",
        "bullet_list",
        "subheading",
        "bullet_list",
    ]

    assert blocks[0]["text"] == "1.50 (May 5, 2010)"
    assert blocks[1]["items"] == [
        "Fixed the first problem.",
        "Fixed the second problem.",
    ]
    assert blocks[2]["text"] == "1.44 (September 2, 2009)"
    assert blocks[3]["items"] == ["Fixed another problem."]

    assert blocks[0]["meta"]["detectors"] == [
        "subheading_updates_star_dash"
    ]


def test_updates_ordinary_asterisk_bullets_remain_a_list():
    """Consecutive asterisk entries remain ordinary bullets."""
    lines = [
        "REV. 2.0 (August 9, 1992):",
        "* Both players could choose the same character.",
        "* New animation added.",
        "* More blood added.",
    ]

    blocks = parse_blocks("updates", lines)

    assert [block["type"] for block in blocks] == [
        "paragraph",
        "bullet_list",
    ]

    assert blocks[0]["text"] == "REV. 2.0 (August 9, 1992):"
    assert blocks[1]["items"] == [
        "Both players could choose the same character.",
        "New animation added.",
        "More blood added.",
    ]


def test_star_dash_pattern_outside_updates_is_unchanged():
    """The new Updates rule must not affect other GH sections."""
    lines = [
        "* Example category",
        "- First entry.",
        "- Second entry.",
    ]

    blocks = parse_blocks("scoring", lines)

    assert [block["type"] for block in blocks] == ["bullet_list"]

    assert blocks[0]["items"] == [
        "Example category",
        "First entry.",
        "Second entry.",
    ]
