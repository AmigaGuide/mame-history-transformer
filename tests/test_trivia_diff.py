"""Regression tests for section-level Gaming History Trivia comparisons."""
import json

import pytest

from mht.audit import trivia_diff


def _block(kind, text, **meta):
    return {"type": kind, "text": text, "meta": {"system": "foo", **meta}}


def _write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records), encoding="utf-8")


def test_trivia_compares_rendered_content_not_parser_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(trivia_diff, "gh_system_trivia_path", lambda v: tmp_path / v / "trivia.json")
    old = {
        "changed": {"sections": {"overview": {"blocks": [_block("paragraph", "Old", block_index=0)]}}},
        "metadata": {"gh_id": 1, "sections_raw": {"overview": "Raw A"},
                     "sections": {"overview": {"blocks": [_block("paragraph", "Same", block_index=0)]}}},
        "unpublished": {"sections": {"trivia": {"blocks": [_block("paragraph", "Old")]}}},
        "absent": {"sections": {"trivia": {"blocks": [_block("paragraph", "Previously here")]}}},
    }
    new = {
        "changed": {"sections": {"overview": {"blocks": [_block("paragraph", "New", block_index=4)]}}},
        "metadata": {"gh_id": 99, "sections_raw": {"overview": "Raw B"},
                     "sections": {"overview": {"blocks": [_block("paragraph", "Same", block_index=99)]}}},
        "unpublished": {"sections": {"trivia": {"blocks": [_block("paragraph", "New")]}}},
    }
    _write(tmp_path / "0288/trivia.json", old)
    _write(tmp_path / "0289/trivia.json", new)
    published = {"changed", "metadata", "absent"}
    result = trivia_diff.compare_trivia_sections("0288", "0289", published, published)
    assert result["changed_machines"] == {"absent": ["trivia"], "changed": ["overview"]}
    assert result["counts"]["machines_with_changed_trivia"] == 2
    assert result["changed_section_counts"] == {"overview": 1, "trivia": 1}


def test_reject_unknown_block_type_instead_of_missing_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(trivia_diff, "gh_system_trivia_path", lambda v: tmp_path / v / "trivia.json")
    _write(tmp_path / "0288/trivia.json", {"a": {"sections": {"overview": {"blocks": [{"type": "mystery"}]}}}})
    _write(tmp_path / "0289/trivia.json", {})
    with pytest.raises(ValueError, match="Unsupported Trivia block"):
        trivia_diff.compare_trivia_sections("0288", "0289", {"a"}, {"a"})
