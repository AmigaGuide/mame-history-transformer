"""Regression tests for emphasised GH Staff entries."""

from mht.inputs.history_blocks import process_section_blocks


def parse_section(tag, lines):
    return process_section_blocks(
        primary="test",
        section_tag=tag,
        lines=lines,
        parsing_state={},
    )


def test_emphasised_staff_pair():
    """An emphasised Staff label becomes a clean pair."""
    blocks = parse_section("staff", [
        "*Sound Director*: Daisuke Matsumoto, Yukihiro Masaki",
    ])

    assert len(blocks) == 1
    assert blocks[0]["type"] == "pair"
    assert blocks[0]["label"] == "Sound Director"
    assert blocks[0]["value"] == (
        "Daisuke Matsumoto, Yukihiro Masaki"
    )


def test_emphasised_staff_subheadings():
    """Standalone emphasised labels become subheadings."""
    blocks = parse_section("staff", [
        "*Team Gremlin*",
        "Programmers: Example Programmer",
        "",
        "*Video Cut Sequences*",
        "Artists: Example Artist",
        "",
        "*Acclaim Team*",
    ])

    headings = [
        block["text"]
        for block in blocks
        if block["type"] == "subheading"
    ]

    assert headings == [
        "Team Gremlin",
        "Video Cut Sequences",
        "Acclaim Team",
    ]


def test_staff_emphasis_preserves_source_provenance():
    """Both types of emphasis retain their source-line indices."""
    blocks = parse_section("staff", [
        "*Team Gremlin*",
        "*Sound Director*: Daisuke Matsumoto",
    ])

    assert [block["type"] for block in blocks] == [
        "subheading",
        "pair",
    ]

    assert blocks[0]["meta"]["filtered_line_start"] == 0
    assert blocks[0]["meta"]["filtered_line_end"] == 0

    assert blocks[1]["meta"]["filtered_line_start"] == 1
    assert blocks[1]["meta"]["filtered_line_end"] == 1


def test_emphasis_rules_do_not_affect_updates():
    """A missing-space asterisk in Updates is not Staff markup."""
    blocks = parse_section("updates", [
        "*Two new kinds of minor enemy appear in the game :",
    ])

    assert not any(
        block["type"] == "pair"
        or block["type"] == "subheading"
        for block in blocks
    )


def test_ordinary_staff_pairs_remain_unchanged():
    """Existing Staff role/value pairs still work normally."""
    blocks = parse_section("staff", [
        "Sound: Yoko Shimomura",
        "Programmers: Macchan",
    ])

    assert [block["type"] for block in blocks] == [
        "pair",
        "pair",
    ]

    assert [block["label"] for block in blocks] == [
        "Sound",
        "Programmers",
    ]
