import copy

from mht.inputs.history_blocks import attach_list_preambles, flag_suspect_hard_wraps


def _mk_para(text, start, end):
    return {"type": "paragraph", "text": text, "meta": {"filtered_line_start": start, "filtered_line_end": end}}

def _mk_list(list_type, items, start, end):
    return {"type": list_type, "items": items, "meta": {"filtered_line_start": start, "filtered_line_end": end}}

def test_preamble_binding_only_on_colon():
    blocks = [
        _mk_para("Intermissions include the following:", 0, 0),
        _mk_list("numbered_list", ["1) Cutscene A", "2) Cutscene B"], 1, 3),
        _mk_para("This paragraph should NOT bind", 5, 5),
        _mk_list("bullet_list", ["- Tip A", "- Tip B"], 6, 7),
    ]
    result = attach_list_preambles(copy.deepcopy(blocks))
    assert result[1]["meta"].get("preamble_text") == "Intermissions include the following:"
    assert result[0]["meta"].get("linked_as_preamble_to") == 1
    assert "preamble_text" not in result[3]["meta"]
    assert "linked_as_preamble_to" not in result[2].get("meta", {})

def test_hard_wrap_flagging_consecutive_paragraphs_only():
    blocks = [
        _mk_para("Line A (end at 0)", 0, 0),
        _mk_para("Line B (immediately next)", 1, 1),   # gap=1 → flag
        _mk_para("Line C (blank line before)", 3, 3),  # gap=2 → no flag
    ]
    result = flag_suspect_hard_wraps(copy.deepcopy(blocks))
    assert result[0]["meta"].get("suspect_hard_wrap") is True
    assert result[1]["meta"].get("suspect_hard_wrap") is True
    assert result[2]["meta"].get("suspect_hard_wrap") is None
