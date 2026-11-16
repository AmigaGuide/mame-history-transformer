"""Focused read-only block-level provenance display checks."""
from mht.preview.app import create_app
from mht.preview.history_block_review import (
    MAX_DETAIL_BLOCKS, build_history_policy_review, build_machine_block_review,
)
from mht.preview.preview_data import PreviewData


def _trivia():
    return {"sections": {"trivia": {"blocks": [
        {"type": "paragraph", "text": "<source> text", "meta": {
            "block_index": 0, "detectors": ["paragraph_per_line"],
            "policy": {"per_line": True, "heuristic_per_line": False},
            "raw_line_start": 4, "raw_line_end": 4,
            "filtered_line_start": 2, "filtered_line_end": 2,
            "text_hash": "deadbeef", "suppressions": []}},
        {"type": "pair", "label": "Label", "value": "Value", "meta": {
            "block_index": 1, "detectors": ["pair_colon"],
            "policy": {"per_line": True, "heuristic_per_line": True},
            "suppressions": ["example_rule"]}}
    ]}}}


def _data(trivia=None, summary=None):
    return PreviewData(wiki_doc={}, wiki_games={},
        trivia_by_machine={"pacman": trivia if trivia is not None else _trivia()},
        mame_machines={"pacman": {"description": "Pac-Man"}},
        mame_summary={}, history_summary=summary if summary is not None else {},
        ini_summary={}, transform_summary={}, machine_order=["pacman"])


def test_all_block_types_and_detector_counts_are_preserved():
    r = build_machine_block_review(_trivia())
    assert r["count"] == 2 and r["heuristic_blocks"] == 1
    assert r["suppression_marked_blocks"] == 1
    assert ("paragraph", 1) in r["kinds"] and ("pair_colon", 1) in r["detectors"]
    assert r["rows"][0]["raw_start"] == 4 and r["rows"][0]["filtered_start"] == 2


def test_malformed_records_do_not_invent_metadata():
    r = build_machine_block_review({"sections": {"trivia": {"blocks": [{"type": "paragraph", "text": "x"}, None]}}})
    assert r["count"] == 1 and r["missing_meta"] == 1
    assert r["rows"][0]["raw_start"] is None
    assert build_machine_block_review({})["has_evidence"] is False


def test_all_blocks_are_counted_but_detail_is_bounded():
    b = _trivia()["sections"]["trivia"]["blocks"][0]
    t = {"sections": {"trivia": {"blocks": [b] * (MAX_DETAIL_BLOCKS + 4)}}}
    r = build_machine_block_review(t)
    assert r["count"] == MAX_DETAIL_BLOCKS + 4
    assert len(r["rows"]) == MAX_DETAIL_BLOCKS and r["omitted"] == 4


def test_summary_policy_counts_are_section_invocations_not_block_counts():
    r = build_history_policy_review({"provenance_qc": {
        "blocks_with_suppressions": 7,
        "policy_counts": {"updates": {"per_line": 4, "heuristic_per_line": 3}}}})
    assert r["rows"] == [{"section": "updates", "per_line": 4, "heuristic": 3}]
    assert r["blocks_with_suppressions"] == 7
    assert build_history_policy_review({"provenance_qc": {"blocks_with_suppressions": True}})["blocks_with_suppressions"] is None


def test_game_page_read_only_block_metadata_escapes_source():
    app = create_app(_data(), version="0289")
    app.config.update(TESTING=True)
    html = app.test_client().get("/game/pacman").get_data(as_text=True)
    assert 'id="block-provenance"' in html
    assert 'href="#block-provenance"' in html
    assert "paragraph_per_line" in html and "deadbeef" in html
    assert "&lt;source&gt;" in html and "<source>" not in html
    assert "source line" in html.lower()


def test_history_summary_displays_aggregate_policy_usage():
    summary = {"provenance_qc": {"blocks_with_suppressions": 7,
        "policy_counts": {"updates": {"per_line": 4, "heuristic_per_line": 3}}}}
    app = create_app(_data(summary=summary), version="0289")
    app.config.update(TESTING=True)
    html = app.test_client().get("/summary/history").get_data(as_text=True)
    assert "Block processing policies" in html
    assert "updates" in html and "7" in html


def test_no_block_metadata_does_not_create_block_section():
    app = create_app(_data(trivia={"sections": {}}), version="0289")
    app.config.update(TESTING=True)
    html = app.test_client().get("/game/pacman").get_data(as_text=True)
    assert 'id="block-provenance"' not in html
