"""Regression tests for unmarked continuations in GH bullet lists."""

from mht.inputs.history_blocks import process_section_blocks


def parse_scoring(lines):
    """Classify scoring lines using the production block parser."""
    return process_section_blocks(
        primary="toobin",
        section_tag="scoring",
        lines=lines,
        parsing_state={},
    )


def test_unmarked_explanations_preserve_list_continuity():
    """
    Unmarked lines within an uninterrupted list belong to the
    preceding item, rather than splitting one logical list.

    A newline preserves the boundary between the marked description
    and its additional explanation without changing the JSON schema.
    """
    lines = [
        "",
        "The player can score points by :",
        "* Time of Travel : Points for travelling down the river.",
        "* Passing through Gates. Gates award different points.",
        "Swishing a gate increases the score multiplier.",
        "* Score Multiplier. Swishing increases the multiplier.",
        "Missing a gate reduces the multiplier.",
        "* Treasures. Collect treasures for additional points.",
        "* Warp. Warping awards bonus points.",
    ]

    blocks = parse_scoring(lines)

    assert [block["type"] for block in blocks] == [
        "paragraph",
        "bullet_list",
    ]

    assert blocks[0]["text"] == "The player can score points by :"

    assert blocks[1]["items"] == [
        "Time of Travel : Points for travelling down the river.",
        (
            "Passing through Gates. Gates award different points.\n"
            "Swishing a gate increases the score multiplier."
        ),
        (
            "Score Multiplier. Swishing increases the multiplier.\n"
            "Missing a gate reduces the multiplier."
        ),
        "Treasures. Collect treasures for additional points.",
        "Warp. Warping awards bonus points.",
    ]

    assert blocks[1]["meta"]["filtered_line_start"] == 2
    assert blocks[1]["meta"]["filtered_line_end"] == 8


def test_blank_line_ends_list_continuation():
    """A blank line prevents an unmarked line joining a list item."""
    lines = [
        "* Gates award points.",
        "",
        "Additional scoring information.",
    ]

    blocks = parse_scoring(lines)

    assert [block["type"] for block in blocks] == [
        "bullet_list",
        "paragraph",
    ]
