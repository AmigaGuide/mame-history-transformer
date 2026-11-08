"""Regression tests for named topics in GH Tips and Tricks."""

from mht.inputs.history_blocks import process_section_blocks


def parse_tips(lines):
    """Classify source lines using the production Tips and Tricks parser."""
    return process_section_blocks(
        primary="test",
        section_tag="tips and tricks",
        lines=lines,
        parsing_state={},
    )


def test_repeated_named_tips_without_introduction():
    """
    Repeated named tips can form subheadings without an introductory
    paragraph, provided each is separated by a blank line.
    """
    lines = [
        "",
        "* Ball Speed : besides the slowest ball speed, there are three speed-ups.",
        "",
        "* Ball Direction : when the ball hits the paddle, it rebounds.",
    ]

    blocks = parse_tips(lines)

    assert [block["type"] for block in blocks] == [
        "subheading",
        "paragraph",
        "subheading",
        "paragraph",
    ]

    assert [blocks[0]["text"], blocks[2]["text"]] == [
        "Ball Speed",
        "Ball Direction",
    ]

    assert blocks[1]["text"].startswith("Besides")
    assert blocks[3]["text"].startswith("When")

    # Splitting a marked line must not invent source positions.
    assert blocks[0]["meta"]["filtered_line_start"] == 1
    assert blocks[1]["meta"]["filtered_line_start"] == 1
    assert blocks[2]["meta"]["filtered_line_start"] == 3
    assert blocks[3]["meta"]["filtered_line_start"] == 3


def test_named_tip_with_additional_paragraphs():
    """
    A named tip can have explanatory lines following its initial
    description, as seen in Attack from Mars.
    """
    lines = [
        "",
        "* Objectives : the main objective is to Rule the Universe.",
        "Your progress is shown by six blue lights.",
        "",
        "* Skill Shots : there are two skill shots available.",
        "Holding the left flipper qualifies for a Super Skill Shot.",
        "A brief ball saver is also available.",
    ]

    blocks = parse_tips(lines)

    assert [block["type"] for block in blocks] == [
        "subheading",
        "paragraph",
        "paragraph",
        "subheading",
        "paragraph",
        "paragraph",
        "paragraph",
    ]

    assert blocks[0]["text"] == "Objectives"
    assert blocks[1]["text"] == (
        "The main objective is to Rule the Universe."
    )

    assert blocks[3]["text"] == "Skill Shots"
    assert blocks[4]["text"] == (
        "There are two skill shots available."
    )


def test_explicit_heading_and_numbered_list_remain_intact():
    """
    An explicit heading introducing numbered instructions must not
    be interpreted as a title-description entry.
    """
    lines = [
        "* Playfield Layout :",
        "1) Left Outlane : Standard.",
        "2) Left Inlane : Standard.",
    ]

    blocks = parse_tips(lines)

    assert blocks[0]["type"] == "subheading"
    assert blocks[0]["text"] == "Playfield Layout :"

    assert blocks[1]["type"] == "numbered_list"
    assert len(blocks[1]["items"]) == 2


def test_named_topic_preserves_numbered_list():
    """
    A numbered list within a named topic must not prevent its
    heading from being recognised.
    """
    lines = [
        "",
        "* Saucer Attack Waves : five countries are under attack.",
        "The artefacts under attack are:",
        "1. U.S. - Statue of Liberty.",
        "2. Germany - Brandenburg Gate.",
        "",
        "* Stroke of Luck : several awards are available.",
        "The possible awards are:",
        "1. 25,000,000 points.",
        "2. 50,000,000 points.",
    ]

    blocks = parse_tips(lines)

    assert [block["type"] for block in blocks] == [
        "subheading",
        "paragraph",
        "paragraph",
        "numbered_list",
        "subheading",
        "paragraph",
        "paragraph",
        "numbered_list",
    ]

    assert blocks[0]["text"] == "Saucer Attack Waves"
    assert blocks[3]["items"] == [
        "U.S. - Statue of Liberty.",
        "Germany - Brandenburg Gate.",
    ]

    assert blocks[4]["text"] == "Stroke of Luck"
    assert len(blocks[7]["items"]) == 2


def test_numbered_topic_does_not_interrupt_neighbouring_topics():
    """
    A named topic followed by a numbered-list topic should still
    form a qualifying group of consecutive named topics.
    """
    lines = [
        "",
        "* Concurrent Multiballs : several modes can run together.",
        "There are four different multiballs in this game:",
        "Here is how it all fits together:",
        "",
        "* Extra Balls : there are several ways to get an extra ball.",
        "1. Complete the second Attack Wave.",
        "2. Complete the inlane lamps.",
        "Extra balls are awarded at the scoop.",
    ]

    blocks = parse_tips(lines)

    assert [block["type"] for block in blocks] == [
        "subheading",
        "paragraph",
        "paragraph",
        "paragraph",
        "subheading",
        "paragraph",
        "numbered_list",
        "paragraph",
    ]

    assert [
        block["text"]
        for block in blocks
        if block["type"] == "subheading"
    ] == [
        "Concurrent Multiballs",
        "Extra Balls",
    ]

    assert blocks[3]["text"] == (
        "Here is how it all fits together:"
    )

    assert blocks[6]["items"] == [
        "Complete the second Attack Wave.",
        "Complete the inlane lamps.",
    ]


def test_named_topics_with_descriptions_ending_in_colons():
    """
    A description ending in a colon must not cause a named topic
    to be mistaken for a standalone starred subheading.
    """
    lines = [
        "",
        "* Concurrent Multiballs : there are several multiballs. "
        "Here is how they work :",
        "Regular multiball and Strobe Multiball cannot run together.",
        "",
        "* Extra Balls : there are five ways to earn an extra ball :",
        "1. Complete the second Attack Wave.",
        "2. Complete the inlane lamps.",
    ]

    blocks = parse_tips(lines)

    assert [block["type"] for block in blocks] == [
        "subheading",
        "paragraph",
        "paragraph",
        "subheading",
        "paragraph",
        "numbered_list",
    ]

    assert blocks[0]["text"] == "Concurrent Multiballs"
    assert blocks[1]["text"].endswith(
        "Here is how they work :"
    )

    assert blocks[3]["text"] == "Extra Balls"
    assert blocks[4]["text"] == (
        "There are five ways to earn an extra ball :"
    )

    assert blocks[5]["items"] == [
        "Complete the second Attack Wave.",
        "Complete the inlane lamps.",
    ]

    for index in (0, 3):
        assert (
            "subheading_tips_named_topic"
            in blocks[index]["meta"]["detectors"]
        )


def test_isolated_named_tip_remains_a_bullet():
    """
    One marked title-description entry is insufficient evidence
    of a repeated named-topic structure.
    """
    lines = [
        "",
        "* Bonus Points : collect the hidden treasure.",
        "",
        "The next stage begins automatically.",
    ]

    blocks = parse_tips(lines)

    assert blocks[0]["type"] == "bullet_list"
    assert blocks[0]["items"] == [
        "Bonus Points : collect the hidden treasure."
    ]

    assert not any(
        "subheading_tips_named_topic"
        in block.get("meta", {}).get("detectors", [])
        for block in blocks
    )


def test_consecutive_bullets_without_blank_boundaries():
    """
    Conventional consecutive bullet entries must not be
    promoted merely because they contain titles and colons.
    """
    lines = [
        "* First bonus : collect three objects.",
        "* Second bonus : defeat the final enemy.",
        "* Third bonus : finish before the timer expires.",
    ]

    blocks = parse_tips(lines)

    assert len(blocks) == 1
    assert blocks[0]["type"] == "bullet_list"

    assert blocks[0]["items"] == [
        "First bonus : collect three objects.",
        "Second bonus : defeat the final enemy.",
        "Third bonus : finish before the timer expires.",
    ]
