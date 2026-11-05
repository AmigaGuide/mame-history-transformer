"""Tests for context-aware heading detection in GH Scoring sections."""

from mht.inputs.history_blocks import process_section_blocks


def parse_blocks(section, lines):
    """Parse sample GH lines without loading release artefacts."""
    return process_section_blocks(
        primary="test",
        section_tag=section,
        lines=lines,
        parsing_state={},
    )


def test_scoring_heading_followed_by_pairs():
    """A scoring category followed by pairs becomes a subheading."""
    lines = [
        "* Basic Move",
        "High Punch: 500 points",
        "Low Punch: 500 points",
        "High Kick: 2,000 points",
    ]

    blocks = parse_blocks("scoring", lines)

    assert [block["type"] for block in blocks] == [
        "subheading",
        "pair",
        "pair",
        "pair",
    ]

    assert blocks[0]["text"] == "Basic Move"
    assert blocks[1]["label"] == "High Punch"
    assert blocks[1]["value"] == "500 points"


def test_scoring_uppercase_heading_followed_by_pairs():
    """Uppercase category headings follow the same structural rule."""
    lines = [
        "* ITEMS",
        "Bag of loot : 100-500 points.",
        "Boater : 750 points.",
    ]

    blocks = parse_blocks("scoring", lines)

    assert [block["type"] for block in blocks] == [
        "subheading",
        "pair",
        "pair",
    ]

    assert blocks[0]["text"] == "ITEMS"


def test_scoring_wrapped_bullet_is_not_a_heading():
    """An ordinary wrapped bullet must not become a subheading."""
    lines = [
        "* One of these bubbles must touch exactly one bubble of a group of",
        "similarly coloured bubbles.",
    ]

    blocks = parse_blocks("scoring", lines)

    assert not any(
        block["type"] == "subheading"
        for block in blocks
    )

    assert any(
        block["type"] == "bullet_list"
        and "One of these bubbles must touch" in block["items"][0]
        for block in blocks
    )


def test_scoring_heading_requires_consecutive_pairs():
    """A blank line interrupts the proposed heading pattern."""
    lines = [
        "* Example scoring instruction",
        "",
        "First item: 100 points",
        "Second item: 200 points",
    ]

    blocks = parse_blocks("scoring", lines)

    assert blocks[0]["type"] == "bullet_list"


def test_scoring_heading_rule_is_section_specific():
    """The same pattern outside Scoring keeps its existing behaviour."""
    lines = [
        "* Example category",
        "First item: 100 points",
        "Second item: 200 points",
    ]

    blocks = parse_blocks("technical", lines)

    assert blocks[0]["type"] == "bullet_list"
