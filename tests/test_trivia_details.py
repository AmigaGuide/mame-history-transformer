from mht.audit import trivia_details


def _section(*blocks):
    return {"sections": {"trivia": {"blocks": list(blocks)}}}


def _paragraph(text, line=1):
    return {"type": "paragraph", "text": text, "meta": {"filtered_line_start": line}}


def test_reports_only_changed_paragraph_and_ignores_metadata():
    old = {"xevious": _section(_paragraph("Keep this paragraph."),
                               _paragraph("Released in December 1982 in Japan.", 2))}
    new = {"xevious": _section(_paragraph("Keep this paragraph.", 87),
                               _paragraph("Released on December 22, 1982 in Japan.", 91))}
    result = trivia_details.detail_for_machine("0288", "0289", "xevious",
                                              before_data=old, after_data=new)
    assert "SECTION MODIFIED" in result
    assert "December 1982" in result
    assert "December 22, 1982" in result
    assert "Keep this paragraph" not in result
    assert "filtered_line_start" not in result


def test_inserted_paragraph_does_not_reprint_unchanged_following_blocks():
    first, last = _paragraph("Start"), _paragraph("End")
    old = {"x": _section(first, last)}
    new = {"x": _section(first, _paragraph("New fact"), last)}
    text = trivia_details.detail_for_machine("a", "b", "x", before_data=old, after_data=new)
    assert "+ [paragraph] New fact" in text
    assert "Start" not in text and "End" not in text


def test_section_removal_is_explicit():
    old = {"x": _section(_paragraph("Obsolete description"))}
    new = {"x": {"sections": {}}}
    text = trivia_details.detail_for_machine("a", "b", "x", before_data=old, after_data=new)
    assert "SECTION REMOVED" in text
    assert "- [paragraph] Obsolete description" in text


def test_unchanged_visible_content_returns_empty_even_if_metadata_changes():
    old = {"x": _section(_paragraph("Unchanged", 1))}
    new = {"x": _section(_paragraph("Unchanged", 100))}
    assert trivia_details.detail_for_machine("a", "b", "x", before_data=old, after_data=new) == ""


def test_long_paragraph_only_shows_nearby_change():
    prefix = "Long unchanged opening. " * 40
    suffix = " Long unchanged ending." * 40
    old = {"x": _section(_paragraph(prefix + "July 1991" + suffix))}
    new = {"x": _section(_paragraph(prefix + "25 July 1991" + suffix))}
    text = trivia_details.detail_for_machine("a", "b", "x", before_data=old, after_data=new)
    assert "25 July 1991" in text
    assert len(text) < 500


def test_pair_and_list_changes_are_visible():
    old = {"x": {"sections": {"scoring": {"blocks": [
        {"type": "pair", "label": "Record", "value": "100", "meta": {}},
        {"type": "bullet_list", "items": ["A", "B"], "meta": {}},
    ]}}}}
    new = {"x": {"sections": {"scoring": {"blocks": [
        {"type": "pair", "label": "Record", "value": "150", "meta": {}},
        {"type": "bullet_list", "items": ["A", "C"], "meta": {}},
    ]}}}}
    text = trivia_details.detail_for_machine("a", "b", "x", before_data=old, after_data=new)
    assert "[pair]" in text
    assert "[bullet_list]" in text
    assert "150" in text
